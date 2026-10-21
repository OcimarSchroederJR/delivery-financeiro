"""Dependências FastAPI: casos de uso, papéis permitidos (spec §3.6) e Idempotency-Key."""

from typing import Annotated

from fastapi import Depends, Header, Request

from pagamentos.aplicacao.solicitante import Solicitante
from pagamentos.composicao import CasosDeUso
from plataforma.api.auth import exigir_papeis
from plataforma.auth import Papel, Usuario

HEADER_IDEMPOTENCY_KEY = "Idempotency-Key"
HEADER_RESPOSTA_REPETIDA = "Idempotency-Replayed"


def obter_casos_de_uso(requisicao: Request) -> CasosDeUso:
    casos: CasosDeUso = requisicao.app.state.casos_de_uso
    return casos


def para_solicitante(usuario: Usuario) -> Solicitante:
    return Solicitante(id=usuario.id, papel=usuario.papel.value, token=usuario.token)


CasosDeUsoDep = Annotated[CasosDeUso, Depends(obter_casos_de_uso)]
ClienteOuAdmin = Annotated[Usuario, Depends(exigir_papeis(Papel.CLIENTE, Papel.ADMIN))]
LeitorDaLista = Annotated[
    Usuario, Depends(exigir_papeis(Papel.CLIENTE, Papel.ADMIN, Papel.SERVICO))
]
QuemEstorna = Annotated[Usuario, Depends(exigir_papeis(Papel.ADMIN, Papel.SERVICO))]
IdempotencyKey = Annotated[
    str | None,
    Header(
        alias=HEADER_IDEMPOTENCY_KEY,
        description=(
            "Obrigatório. Chave única da operação (1 a 255 caracteres ASCII visíveis), "
            "válida por 24 h."
        ),
    ),
]
