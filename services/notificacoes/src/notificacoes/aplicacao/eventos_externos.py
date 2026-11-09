"""Entrada de eventos de outras equipes (spec §3.3): valida e grava no outbox.

Funciona como adapter: as Equipes 3 e 4 não precisam conhecer o RabbitMQ.
O relay publica depois em ``financeiro.eventos`` com routing key = ``tipo``.
"""

import json
import unicodedata
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from notificacoes.aplicacao.portas import UnidadeDeTrabalho
from notificacoes.dominio.erros import (
    EnvelopeInvalido,
    TipoDeEventoNaoPermitido,
    TipoDeEventoReservado,
)
from plataforma.envelope import EnvelopeEvento
from plataforma.logs import obter_logger

_log = obter_logger(__name__)

TAMANHO_MAXIMO_ENVELOPE = 64 * 1024
TAMANHO_MAXIMO_ID = 128  # = String(128) de destinatario_id/criado_por no banco
_SUFIXO_ID = "_id"
_CATEGORIAS_PROIBIDAS = frozenset({"Cc", "Zl", "Zp"})  # controle e quebras de linha
PREFIXOS_RESERVADOS = frozenset(
    {"pagamento", "estorno", "avaliacao", "disputa", "notificacao", "tarefa"}
)
PAPEL_ADMIN = "admin"
# Cada sistema só publica os fatos do próprio domínio; admin publica qualquer
# tipo não reservado. Premissa: a Eq. 1 emite papel ``loja`` só para a Eq. 3 e
# ``entregador`` só para a Eq. 4 (não validamos o dono de cada pedido aqui).
PREFIXOS_POR_PAPEL: dict[str, frozenset[str]] = {
    "entregador": frozenset({"entrega"}),
    "loja": frozenset({"pedido"}),
}


@dataclass(frozen=True, slots=True)
class EventoRecebido:
    mensagem_id: uuid.UUID
    novo: bool


def interpretar_corpo(corpo: bytes) -> object:
    if len(corpo) > TAMANHO_MAXIMO_ENVELOPE:
        raise EnvelopeInvalido("O envelope passa de 64 KB.")
    try:
        dados: object = json.loads(corpo)
    except ValueError as erro:  # JSONDecodeError e UnicodeDecodeError
        raise EnvelopeInvalido("O corpo não é um JSON válido.") from erro
    if _tem_caractere_nulo(dados):
        raise EnvelopeInvalido("O envelope não pode ter o caractere nulo (\\u0000).")
    return dados


def _tem_caractere_nulo(valor: object) -> bool:
    # O Postgres não guarda \u0000 em JSONB nem em texto
    if isinstance(valor, str):
        return "\x00" in valor
    if isinstance(valor, dict):
        return any(_tem_caractere_nulo(k) or _tem_caractere_nulo(v) for k, v in valor.items())
    if isinstance(valor, list):
        return any(_tem_caractere_nulo(item) for item in valor)
    return False


def _problema_do_id(valor: Any) -> str | None:
    if not isinstance(valor, str):
        return "Identificadores devem ser texto."
    if not valor or len(valor) > TAMANHO_MAXIMO_ID:
        return f"Identificadores devem ter de 1 a {TAMANHO_MAXIMO_ID} caracteres."
    if any(unicodedata.category(caractere) in _CATEGORIAS_PROIBIDAS for caractere in valor):
        return "Identificadores não podem ter caracteres de controle ou quebras de linha."
    return None


def _validar_ids(dados: Mapping[str, Any]) -> None:
    """Campos ``*_id`` viram destinatário, assunto de e-mail e colunas do banco."""
    detalhes = [
        {"campo": f"dados.{campo}", "mensagem": problema}
        for campo, valor in dados.items()
        if campo.endswith(_SUFIXO_ID) and (problema := _problema_do_id(valor)) is not None
    ]
    if detalhes:
        raise EnvelopeInvalido(detalhes={"detalhes": detalhes})


def validar_envelope(dados: object) -> EnvelopeEvento:
    try:
        envelope = EnvelopeEvento.model_validate(dados)
    except ValidationError as erro:
        detalhes = [
            {
                "campo": ".".join(str(parte) for parte in item["loc"]) or "corpo",
                "mensagem": item["msg"],
            }
            for item in erro.errors(include_input=False, include_url=False)
        ]
        raise EnvelopeInvalido(detalhes={"detalhes": detalhes}) from None
    _validar_ids(envelope.dados)
    return envelope


def exigir_tipo_permitido(tipo: str, papel: str) -> None:
    prefixo = tipo.split(".", 1)[0]
    if prefixo in PREFIXOS_RESERVADOS:
        raise TipoDeEventoReservado(detalhes={"tipo": tipo})
    if papel != PAPEL_ADMIN and prefixo not in PREFIXOS_POR_PAPEL.get(papel, frozenset()):
        raise TipoDeEventoNaoPermitido(detalhes={"tipo": tipo, "papel": papel})


async def receber_evento_externo(
    uow: UnidadeDeTrabalho, dados: object, *, papel: str
) -> EventoRecebido:
    envelope = validar_envelope(dados)
    exigir_tipo_permitido(envelope.tipo, papel)
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
