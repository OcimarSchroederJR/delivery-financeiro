"""Helpers de requisição para testes de API: tokens, cabeçalhos e corpos."""

from typing import Any

from plataforma.auth import EmissorTokenServico, VerificadorComposto
from plataforma.correlation import HEADER_CORRELATION_ID
from plataforma.testes.tokens import (
    SEGREDO_SERVICO_TESTE,
    GeradorDeTokens,
    criar_verificador_de_teste,
)

GERADOR = GeradorDeTokens()
NUMERO_CARTAO_PREFIXO = "411111111111"
TITULAR_TESTE = "Fulano de Tal"


def verificador_de_teste() -> VerificadorComposto:
    return criar_verificador_de_teste(GERADOR)


def token(papel: str = "cliente", sub: str = "cliente-1") -> str:
    if papel == "servico":
        return EmissorTokenServico(SEGREDO_SERVICO_TESTE, servico=sub).emitir()
    return GERADOR.emitir(sub, papel)


def cabecalhos(
    papel: str = "cliente",
    sub: str = "cliente-1",
    *,
    chave: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, str]:
    resultado = {"Authorization": f"Bearer {token(papel, sub)}"}
    if chave is not None:
        resultado["Idempotency-Key"] = chave
    if correlation_id is not None:
        resultado[HEADER_CORRELATION_ID] = correlation_id
    return resultado


def corpo_cartao(
    pedido_id: str = "ped-1", final: str = "0000", *, cvv: str = "123"
) -> dict[str, Any]:
    return {
        "pedido_id": pedido_id,
        "metodo": "cartao_credito",
        "cartao": {
            "numero": NUMERO_CARTAO_PREFIXO + final,
            "titular": TITULAR_TESTE,
            "validade": "12/28",
            "cvv": cvv,
        },
    }


def corpo_pix(pedido_id: str = "ped-1") -> dict[str, Any]:
    return {"pedido_id": pedido_id, "metodo": "pix"}
