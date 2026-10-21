"""Entrada de eventos de outras equipes (spec §3.3): valida e grava no outbox.

Funciona como adapter: as Equipes 3 e 4 não precisam conhecer o RabbitMQ.
O relay publica depois em ``financeiro.eventos`` com routing key = ``tipo``.
"""

import json
import uuid
from dataclasses import dataclass

from pydantic import ValidationError

from notificacoes.aplicacao.portas import UnidadeDeTrabalho
from notificacoes.dominio.erros import EnvelopeInvalido, TipoDeEventoReservado
from plataforma.envelope import EnvelopeEvento
from plataforma.logs import obter_logger

_log = obter_logger(__name__)

TAMANHO_MAXIMO_ENVELOPE = 64 * 1024
PREFIXOS_RESERVADOS = frozenset(
    {"pagamento", "estorno", "avaliacao", "disputa", "notificacao", "tarefa"}
)


@dataclass(frozen=True, slots=True)
class EventoRecebido:
    mensagem_id: uuid.UUID
    novo: bool


def interpretar_corpo(corpo: bytes) -> object:
    if len(corpo) > TAMANHO_MAXIMO_ENVELOPE:
        raise EnvelopeInvalido("O envelope passa de 64 KB.")
    try:
        return json.loads(corpo)
    except ValueError as erro:  # JSONDecodeError e UnicodeDecodeError
        raise EnvelopeInvalido("O corpo não é um JSON válido.") from erro


def validar_envelope(dados: object) -> EnvelopeEvento:
    try:
        return EnvelopeEvento.model_validate(dados)
    except ValidationError as erro:
        detalhes = [
            {
                "campo": ".".join(str(parte) for parte in item["loc"]) or "corpo",
                "mensagem": item["msg"],
            }
            for item in erro.errors(include_input=False, include_url=False)
        ]
        raise EnvelopeInvalido(detalhes={"detalhes": detalhes}) from None


async def receber_evento_externo(uow: UnidadeDeTrabalho, dados: object) -> EventoRecebido:
    envelope = validar_envelope(dados)
    if envelope.tipo.split(".", 1)[0] in PREFIXOS_RESERVADOS:
        raise TipoDeEventoReservado(detalhes={"tipo": envelope.tipo})
    async with uow:
        novo = await uow.eventos_externos.registrar_se_novo(envelope)
        await uow.commit()
    _log.info(
        "evento_externo_recebido",
        tipo=envelope.tipo,
        mensagem_id=str(envelope.mensagem_id),
        duplicado=not novo,
    )
    return EventoRecebido(mensagem_id=envelope.mensagem_id, novo=novo)
