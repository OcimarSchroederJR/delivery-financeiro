"""Dependências FastAPI de autenticação/autorização.

- ``UsuarioAtual``/``usuario_atual``: qualquer papel de usuário (cliente, loja,
  entregador, admin). Token de serviço é recusado (403).
- ``exigir_papeis(...)``: só os papéis listados; ``Papel.SERVICO`` só passa se listado.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from plataforma.auth import PAPEIS_DE_USUARIO, Papel, Usuario, VerificadorDeToken
from plataforma.erros import ErroAcessoNegado, ErroNaoAutenticado

_esquema_bearer = HTTPBearer(
    auto_error=False,
    description="JWT da Equipe 1 (ou token de serviço interno da Equipe 5).",
)
Credenciais = Annotated[HTTPAuthorizationCredentials | None, Depends(_esquema_bearer)]


def configurar_autenticacao(app: FastAPI, verificador: VerificadorDeToken) -> None:
    app.state.verificador_token = verificador


async def _autenticar(
    requisicao: Request, credenciais: HTTPAuthorizationCredentials | None
) -> Usuario:
    if credenciais is None or not credenciais.credentials:
        raise ErroNaoAutenticado()
    verificador: VerificadorDeToken | None = getattr(
        requisicao.app.state, "verificador_token", None
    )
    if verificador is None:
        raise RuntimeError("VerificadorDeToken não configurado: chame configurar_autenticacao")
    return await verificador.verificar(credenciais.credentials)


def exigir_papeis(*papeis: Papel) -> Callable[..., Awaitable[Usuario]]:
    permitidos = frozenset(papeis)

    async def dependencia(requisicao: Request, credenciais: Credenciais) -> Usuario:
        usuario = await _autenticar(requisicao, credenciais)
        if usuario.papel not in permitidos:
            raise ErroAcessoNegado()
        return usuario

    return dependencia


usuario_atual = exigir_papeis(*PAPEIS_DE_USUARIO)

UsuarioAtual = Annotated[Usuario, Depends(usuario_atual)]
