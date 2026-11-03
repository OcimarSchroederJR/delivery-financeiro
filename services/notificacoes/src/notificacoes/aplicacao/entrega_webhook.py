"""Consumidor de ``notificacoes.webhooks``: POST assinado com HMAC (spec §4.2).

Cada tentativa vira uma ``EntregaWebhook``. Qualquer resposta fora de 2xx,
timeout (5 s no total) ou erro de rede é falha e pede retentativa; são até 6
tentativas (1 inicial + 5 retentativas) e, depois da última falha, a
notificação fica ``falhou`` e a mensagem vai para a DLQ.

A chamada HTTP acontece **fora** de transação: (1) lê e valida com a linha
travada e faz commit; (2) chama o receptor; (3) numa nova transação, grava a
tentativa e o novo estado. Um receptor lento não segura trava nem conexão do
banco. Se outra entrega concorrente (mensagem duplicada) já mudou a
notificação, a tentativa é registrada e o desfecho é ``ignorada``: a entrega é
pelo menos uma vez (o receptor deduplica por ``X-Evento-Id``).
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from notificacoes.aplicacao.portas import (
    EntregadorDeWebhook,
    FabricaUow,
    ResultadoEntrega,
    SegredoIlegivel,
)
from notificacoes.aplicacao.tarefas import Desfecho, Tarefa
from notificacoes.dominio.assinatura_hmac import cabecalhos_da_entrega
from notificacoes.dominio.entrega import EntregaWebhook
from plataforma.envelope import EnvelopeEvento
from plataforma.logs import obter_logger
from plataforma.tempo import agora_utc

_log = obter_logger(__name__)

MOTIVO_SEGREDO_ILEGIVEL = (
    "Segredo da assinatura ilegível (chave de cifragem trocada ou dado corrompido); "
    "recadastre o webhook."
)


def serializar_evento(evento: EnvelopeEvento) -> bytes:
    """Bytes exatos do corpo enviado (e assinado)."""
    return json.dumps(evento.para_json(), ensure_ascii=False, separators=(",", ":")).encode()


@dataclass(frozen=True, slots=True)
class _Preparo:
    assinatura_id: uuid.UUID
    url: str
    segredo: str
    tentativas_antes: int


class EntregarWebhook:
    def __init__(
        self,
        fabrica_uow: FabricaUow,
        entregador: EntregadorDeWebhook,
        *,
        max_retentativas: int,
        agora: Callable[[], datetime] = agora_utc,
    ) -> None:
        self._fabrica_uow = fabrica_uow
        self._entregador = entregador
        self._max_retentativas = max_retentativas
        self._agora = agora

    async def executar(self, tarefa: Tarefa) -> Desfecho:
        preparo = await self._preparar(tarefa)
        if isinstance(preparo, Desfecho):
            return preparo
        momento = self._agora()
        corpo = serializar_evento(tarefa.evento)
        cabecalhos = cabecalhos_da_entrega(
            segredo=preparo.segredo,
            timestamp=int(momento.timestamp()),
            corpo=corpo,
            evento_id=str(tarefa.evento.mensagem_id),
            evento_tipo=tarefa.evento.tipo,
        )
        resultado = await self._entregador.entregar(preparo.url, corpo, cabecalhos)
        return await self._registrar(tarefa, preparo, resultado, momento)

    async def _preparar(self, tarefa: Tarefa) -> _Preparo | Desfecho:
        """Fase 1: valida com a linha travada e libera a trava antes do HTTP."""
        async with self._fabrica_uow() as uow:
            notificacao = await uow.notificacoes.obter_para_atualizar(tarefa.notificacao_id)
            if notificacao is None or not notificacao.pendente:
                return Desfecho.ignorada("Notificação inexistente ou já finalizada.")
            assinatura = (
                await uow.assinaturas.obter(notificacao.assinatura_id)
                if notificacao.assinatura_id is not None
                else None
            )
            if assinatura is None or not assinatura.ativa:
                notificacao.cancelar("Assinatura removida antes da entrega.")
                await uow.notificacoes.atualizar(notificacao)
                await uow.commit()
                return Desfecho.ignorada("Assinatura removida.")
            try:
                segredo = await uow.assinaturas.obter_segredo(assinatura.id)
            except SegredoIlegivel:
                # Falha definitiva só desta assinatura; as outras seguem normalmente.
                await uow.entregas.adicionar(
                    EntregaWebhook.registrar(
                        assinatura_id=assinatura.id,
                        mensagem_id=tarefa.evento.mensagem_id,
                        tentativa=notificacao.tentativas + 1,
                        status_http=None,
                        duracao_ms=0,
                        erro=MOTIVO_SEGREDO_ILEGIVEL,
                        agora=self._agora(),
                    )
                )
                notificacao.falhar_definitivamente(MOTIVO_SEGREDO_ILEGIVEL)
                await uow.notificacoes.atualizar(notificacao)
                await uow.commit()
                self._logar(tarefa, assinatura.id, notificacao.tentativas, None)
                return Desfecho.desistir(MOTIVO_SEGREDO_ILEGIVEL)
            await uow.commit()  # nada mudou: só libera a trava
        return _Preparo(assinatura.id, assinatura.url, segredo, notificacao.tentativas)

    async def _registrar(
        self,
        tarefa: Tarefa,
        preparo: _Preparo,
        resultado: ResultadoEntrega,
        momento: datetime,
    ) -> Desfecho:
        """Fase 3: grava a tentativa e o novo estado numa transação curta."""
        async with self._fabrica_uow() as uow:
            await uow.entregas.adicionar(
                EntregaWebhook.registrar(
                    assinatura_id=preparo.assinatura_id,
                    mensagem_id=tarefa.evento.mensagem_id,
                    tentativa=preparo.tentativas_antes + 1,
                    status_http=resultado.status_http,
                    duracao_ms=resultado.duracao_ms,
                    erro=resultado.erro,
                    agora=momento,
                )
            )
            notificacao = await uow.notificacoes.obter_para_atualizar(tarefa.notificacao_id)
            if (
                notificacao is None
                or not notificacao.pendente
                or notificacao.tentativas != preparo.tentativas_antes
            ):
                await uow.commit()
                return Desfecho.ignorada("Notificação atualizada por outra entrega.")
            if resultado.sucesso:
                notificacao.registrar_envio(agora=momento)
                desfecho = Desfecho.concluida()
            else:
                motivo = resultado.descricao_falha()
                retentativa = notificacao.registrar_falha(
                    motivo, max_retentativas=self._max_retentativas
                )
                desfecho = (
                    Desfecho.desistir(motivo)
                    if retentativa is None
                    else Desfecho.repetir(retentativa, motivo)
                )
            await uow.notificacoes.atualizar(notificacao)
            await uow.commit()
        self._logar(tarefa, preparo.assinatura_id, notificacao.tentativas, desfecho)
        return desfecho

    def _logar(
        self,
        tarefa: Tarefa,
        assinatura_id: uuid.UUID,
        tentativas: int,
        desfecho: Desfecho | None,
    ) -> None:
        motivo = MOTIVO_SEGREDO_ILEGIVEL if desfecho is None else desfecho.motivo
        registrar = _log.info if motivo is None else _log.warning
        registrar(
            "webhook_entregue" if motivo is None else "webhook_falhou",
            notificacao_id=str(tarefa.notificacao_id),
            assinatura_id=str(assinatura_id),
            tipo_evento=tarefa.evento.tipo,
            tentativas=tentativas,
            desfecho="desistir" if desfecho is None else desfecho.tipo.value,
            motivo=motivo,
        )
