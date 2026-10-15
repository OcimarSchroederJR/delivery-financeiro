"""Consumidor de ``notificacoes.webhooks``: POST assinado com HMAC (spec §4.2).

Cada tentativa vira uma ``EntregaWebhook``. Qualquer resposta fora de 2xx,
timeout (5 s no total) ou erro de rede é falha e pede retentativa; depois da
5ª retentativa a notificação fica ``falhou`` e a mensagem vai para a DLQ.
"""

import json
from collections.abc import Callable
from datetime import datetime

from notificacoes.aplicacao.portas import EntregadorDeWebhook, FabricaUow, UnidadeDeTrabalho
from notificacoes.aplicacao.tarefas import Desfecho, Tarefa
from notificacoes.dominio.assinatura import AssinaturaWebhook
from notificacoes.dominio.assinatura_hmac import cabecalhos_da_entrega
from notificacoes.dominio.entrega import EntregaWebhook
from notificacoes.dominio.notificacao import Notificacao
from plataforma.envelope import EnvelopeEvento
from plataforma.logs import obter_logger
from plataforma.tempo import agora_utc

_log = obter_logger(__name__)


def serializar_evento(evento: EnvelopeEvento) -> bytes:
    """Bytes exatos do corpo enviado (e assinado)."""
    return json.dumps(evento.para_json(), ensure_ascii=False, separators=(",", ":")).encode()


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
            desfecho = await self._entregar(uow, notificacao, assinatura, tarefa.evento)
            await uow.notificacoes.atualizar(notificacao)
            await uow.commit()
        registrar = _log.info if desfecho.motivo is None else _log.warning
        registrar(
            "webhook_entregue" if desfecho.motivo is None else "webhook_falhou",
            notificacao_id=str(notificacao.id),
            assinatura_id=str(assinatura.id),
            tipo_evento=notificacao.tipo_evento,
            tentativas=notificacao.tentativas,
            desfecho=desfecho.tipo.value,
            motivo=desfecho.motivo,
        )
        return desfecho

    async def _entregar(
        self,
        uow: UnidadeDeTrabalho,
        notificacao: Notificacao,
        assinatura: AssinaturaWebhook,
        evento: EnvelopeEvento,
    ) -> Desfecho:
        momento = self._agora()
        corpo = serializar_evento(evento)
        cabecalhos = cabecalhos_da_entrega(
            segredo=assinatura.segredo,
            timestamp=int(momento.timestamp()),
            corpo=corpo,
            evento_id=str(evento.mensagem_id),
            evento_tipo=evento.tipo,
        )
        resultado = await self._entregador.entregar(assinatura.url, corpo, cabecalhos)
        await uow.entregas.adicionar(
            EntregaWebhook.registrar(
                assinatura_id=assinatura.id,
                mensagem_id=evento.mensagem_id,
                tentativa=notificacao.tentativas + 1,
                status_http=resultado.status_http,
                duracao_ms=resultado.duracao_ms,
                erro=resultado.erro,
                agora=momento,
            )
        )
        if resultado.sucesso:
            notificacao.registrar_envio(agora=momento)
            return Desfecho.concluida()
        motivo = resultado.descricao_falha()
        retentativa = notificacao.registrar_falha(motivo, max_retentativas=self._max_retentativas)
        if retentativa is None:
            return Desfecho.desistir(motivo)
        return Desfecho.repetir(retentativa, motivo)
