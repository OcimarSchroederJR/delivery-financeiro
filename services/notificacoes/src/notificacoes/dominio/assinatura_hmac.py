"""Assinatura HMAC-SHA256 das entregas de webhook (spec §4.2).

O receptor recalcula ``HMAC-SHA256(segredo, "<timestamp>.<corpo>")`` com o
corpo **exatamente** como recebido e compara com ``X-Assinatura``.
"""

import hashlib
import hmac
import secrets

PREFIXO = "sha256="
HEADER_ASSINATURA = "X-Assinatura"
HEADER_TIMESTAMP = "X-Assinatura-Timestamp"
HEADER_EVENTO_ID = "X-Evento-Id"
HEADER_EVENTO_TIPO = "X-Evento-Tipo"


def assinar(segredo: str, timestamp: int, corpo: bytes) -> str:
    mensagem = f"{timestamp}.".encode() + corpo
    return PREFIXO + hmac.new(segredo.encode(), mensagem, hashlib.sha256).hexdigest()


def assinatura_valida(
    segredo: str,
    timestamp: int,
    corpo: bytes,
    recebida: str,
    *,
    agora: int,
    tolerancia_segundos: int = 300,
) -> bool:
    """Como o receptor deve validar (documentado no guia de integração)."""
    if abs(agora - timestamp) > tolerancia_segundos:
        return False
    return hmac.compare_digest(assinar(segredo, timestamp, corpo), recebida)


def cabecalhos_da_entrega(
    *, segredo: str, timestamp: int, corpo: bytes, evento_id: str, evento_tipo: str
) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        HEADER_ASSINATURA: assinar(segredo, timestamp, corpo),
        HEADER_TIMESTAMP: str(timestamp),
        HEADER_EVENTO_ID: evento_id,
        HEADER_EVENTO_TIPO: evento_tipo,
    }


def gerar_segredo() -> str:
    """Segredo novo por assinatura (256 bits, URL-safe)."""
    return secrets.token_urlsafe(32)
