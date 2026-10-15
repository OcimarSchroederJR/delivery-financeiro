"""Consumidor de ``notificacoes.emails``: busca o perfil, renderiza e envia.

Falha transitória (Eq. 1 fora, SMTP fora) → retentativa pelas filas com TTL
(spec §4.2: "falha ao buscar o perfil … não é perdida"). Falha definitiva
(perfil inexistente, sem e-mail, evento incompleto) → ``falhou`` + DLQ.
"""

from collections.abc import Callable
from datetime import datetime

from notificacoes.aplicacao.portas import (
    ClientePerfis,
    EnviadorDeEmail,
    FabricaUow,
    FalhaNoEnvioDeEmail,
    PerfilInvalido,
    PerfilNaoEncontrado,
)
from notificacoes.aplicacao.tarefas import Desfecho, Tarefa
from notificacoes.dominio.erros import DadosDoEventoInsuficientes
from notificacoes.dominio.notificacao import Notificacao
from notificacoes.dominio.templates import modelo_para
from plataforma.envelope import EnvelopeEvento
from plataforma.erros import ErroAplicacao, ErroDependenciaIndisponivel
from plataforma.logs import obter_logger
from plataforma.tempo import agora_utc

_log = obter_logger(__name__)

NOME_OPERACOES = "equipe de operações"
NOME_PADRAO_CLIENTE = "cliente"


def descrever_erro(erro: Exception) -> str:
    mensagem = erro.mensagem if isinstance(erro, ErroAplicacao) else str(erro)
    return f"{type(erro).__name__}: {mensagem}"


class EnviarEmail:
    def __init__(
        self,
        fabrica_uow: FabricaUow,
        perfis: ClientePerfis,
        enviador: EnviadorDeEmail,
        *,
        max_retentativas: int,
        agora: Callable[[], datetime] = agora_utc,
    ) -> None:
        self._fabrica_uow = fabrica_uow
        self._perfis = perfis
        self._enviador = enviador
        self._max_retentativas = max_retentativas
        self._agora = agora

    async def executar(self, tarefa: Tarefa) -> Desfecho:
        async with self._fabrica_uow() as uow:
            notificacao = await uow.notificacoes.obter_para_atualizar(tarefa.notificacao_id)
            if notificacao is None or not notificacao.pendente:
                return Desfecho.ignorada("Notificação inexistente ou já finalizada.")
            desfecho = await self._tentar(notificacao, tarefa.evento)
            await uow.notificacoes.atualizar(notificacao)
            await uow.commit()
        if desfecho.motivo is None:
            _log.info(
                "email_enviado",
                notificacao_id=str(notificacao.id),
                tipo_evento=notificacao.tipo_evento,
                tentativas=notificacao.tentativas,
            )
        else:
            _log.warning(
                "email_falhou",
                notificacao_id=str(notificacao.id),
                tipo_evento=notificacao.tipo_evento,
                tentativas=notificacao.tentativas,
                desfecho=desfecho.tipo.value,
                motivo=desfecho.motivo,
            )
        return desfecho

    async def _tentar(self, notificacao: Notificacao, evento: EnvelopeEvento) -> Desfecho:
        try:
            modelo = modelo_para(evento.tipo)
            if modelo is None:
                raise DadosDoEventoInsuficientes(f"Não há template para {evento.tipo}.")
            destino, nome = await self._destinatario(notificacao)
            email = modelo.renderizar(evento.dados, nome=nome)
            await self._enviador.enviar(para=destino, assunto=email.assunto, corpo=email.corpo)
        except (PerfilNaoEncontrado, PerfilInvalido, DadosDoEventoInsuficientes) as erro:
            motivo = descrever_erro(erro)
            notificacao.falhar_definitivamente(motivo)
            return Desfecho.desistir(motivo)
        except (ErroDependenciaIndisponivel, FalhaNoEnvioDeEmail) as erro:
            motivo = descrever_erro(erro)
            retentativa = notificacao.registrar_falha(
                motivo, max_retentativas=self._max_retentativas
            )
            if retentativa is None:
                return Desfecho.desistir(motivo)
            return Desfecho.repetir(retentativa, motivo)
        notificacao.registrar_envio(agora=self._agora(), destino=destino)
        return Desfecho.concluida()

    async def _destinatario(self, notificacao: Notificacao) -> tuple[str, str]:
        if notificacao.destino is not None:
            return notificacao.destino, NOME_OPERACOES
        if notificacao.destinatario_id is None:
            raise DadosDoEventoInsuficientes("Notificação de e-mail sem destinatário.")
        perfil = await self._perfis.obter(notificacao.destinatario_id)
        return perfil.email, perfil.nome or NOME_PADRAO_CLIENTE
