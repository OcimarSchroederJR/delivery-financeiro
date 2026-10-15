"""Autenticação: porta ``VerificadorDeToken`` e adapters (spec §3.6).

- ``VerificadorJwks``: tokens RS256 da Eq. 1, chaves do JWKS em cache com TTL;
  se a Eq. 1 cair, continua com a última chave conhecida.
- ``EmissorTokenServico``/``VerificadorTokenServico``: JWT HS256 interno da equipe
  (``iss = "financeiro-eq5"``, papel ``servico``) para chamadas de workers.
- ``VerificadorComposto``: escolhe o verificador pelo ``iss`` (sem confiar nele:
  cada verificador valida assinatura e algoritmo próprios).
"""

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

import httpx
import jwt

from plataforma.config import ConfiguracaoBase
from plataforma.erros import ErroDependenciaIndisponivel, ErroNaoAutenticado
from plataforma.logs import obter_logger

_log = obter_logger(__name__)

EMISSOR_INTERNO = "financeiro-eq5"
TOLERANCIA_RELOGIO_SEGUNDOS = 30


class Papel(StrEnum):
    CLIENTE = "cliente"
    LOJA = "loja"
    ENTREGADOR = "entregador"
    ADMIN = "admin"
    SERVICO = "servico"


PAPEIS_DE_USUARIO = frozenset({Papel.CLIENTE, Papel.LOJA, Papel.ENTREGADOR, Papel.ADMIN})


@dataclass(frozen=True, slots=True)
class Usuario:
    id: str
    papel: Papel
    token: str = field(repr=False)
    emissor: str | None = None


class VerificadorDeToken(Protocol):
    async def verificar(self, token: str) -> Usuario: ...


def _papel_de_usuario(valor: object) -> Papel:
    """Papel vindo da Eq. 1. Aceita string ou lista; nunca concede ``servico``."""
    candidatos = valor if isinstance(valor, list) else [valor]
    for candidato in candidatos:
        if isinstance(candidato, str):
            try:
                papel = Papel(candidato.lower())
            except ValueError:
                continue
            if papel in PAPEIS_DE_USUARIO:
                return papel
    raise ErroNaoAutenticado("Token sem papel reconhecido.")


class VerificadorJwks:
    def __init__(
        self,
        url_jwks: str,
        *,
        cliente: httpx.AsyncClient | None = None,
        ttl_segundos: float = 300.0,
        claim_papel: str = "papel",
        emissor: str | None = None,
        audiencia: str | None = None,
        intervalo_minimo_recarga: float = 10.0,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url_jwks
        self._cliente = cliente or httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.0))
        self._ttl = ttl_segundos
        self._claim_papel = claim_papel
        self._emissor = emissor
        self._audiencia = audiencia
        self._intervalo_minimo = intervalo_minimo_recarga
        self._relogio = relogio
        self._chaves: dict[str | None, jwt.PyJWK] | None = None
        self._carregado_em = 0.0
        self._ultima_tentativa: float | None = None
        self._trava = asyncio.Lock()

    async def verificar(self, token: str) -> Usuario:
        try:
            cabecalho = jwt.get_unverified_header(token)
        except jwt.PyJWTError as erro:
            raise ErroNaoAutenticado() from erro
        if cabecalho.get("alg") != "RS256":
            raise ErroNaoAutenticado("Algoritmo de assinatura não aceito.")
        chave = await self._chave(cabecalho.get("kid"))
        try:
            claims = jwt.decode(
                token,
                chave.key,
                algorithms=["RS256"],
                issuer=self._emissor,
                audience=self._audiencia,
                leeway=TOLERANCIA_RELOGIO_SEGUNDOS,
                options={"require": ["exp", "sub"], "verify_aud": self._audiencia is not None},
            )
        except jwt.PyJWTError as erro:
            raise ErroNaoAutenticado() from erro
        return Usuario(
            id=str(claims["sub"]),
            papel=_papel_de_usuario(claims.get(self._claim_papel)),
            token=token,
            emissor=claims.get("iss"),
        )

    async def _chave(self, kid: str | None) -> jwt.PyJWK:
        async with self._trava:
            expirado = self._chaves is None or self._relogio() - self._carregado_em >= self._ttl
            if expirado and self._pode_recarregar():
                await self._recarregar()
            chave = self._procurar(kid)
            if chave is None and self._pode_recarregar():
                await self._recarregar()
                chave = self._procurar(kid)
        if chave is None:
            raise ErroNaoAutenticado("Chave de assinatura desconhecida.")
        return chave

    def _pode_recarregar(self) -> bool:
        if self._ultima_tentativa is None:
            return True
        return self._relogio() - self._ultima_tentativa >= self._intervalo_minimo

    def _procurar(self, kid: str | None) -> jwt.PyJWK | None:
        if not self._chaves:
            return None
        if kid is None and len(self._chaves) == 1:
            return next(iter(self._chaves.values()))
        return self._chaves.get(kid)

    async def _recarregar(self) -> None:
        self._ultima_tentativa = self._relogio()
        try:
            resposta = await self._cliente.get(self._url)
            resposta.raise_for_status()
            conjunto = jwt.PyJWKSet.from_dict(resposta.json())
        except (httpx.HTTPError, jwt.PyJWTError, ValueError) as erro:
            _log.warning(
                "jwks_indisponivel",
                erro=type(erro).__name__,
                usando_cache=self._chaves is not None,
            )
            if self._chaves is None:
                raise ErroDependenciaIndisponivel("identidade") from erro
            return
        self._chaves = {chave.key_id: chave for chave in conjunto.keys}
        self._carregado_em = self._relogio()
        _log.info("jwks_carregado", chaves=len(self._chaves))

    async def fechar(self) -> None:
        await self._cliente.aclose()


class EmissorTokenServico:
    def __init__(
        self,
        segredo: str,
        *,
        servico: str,
        validade_segundos: int = 300,
        relogio: Callable[[], float] = time.time,
    ) -> None:
        self._segredo = segredo
        self._servico = servico
        self._validade = validade_segundos
        self._relogio = relogio

    def emitir(self) -> str:
        agora = int(self._relogio())
        claims: dict[str, Any] = {
            "iss": EMISSOR_INTERNO,
            "sub": self._servico,
            "papel": Papel.SERVICO.value,
            "iat": agora,
            "exp": agora + self._validade,
        }
        return str(jwt.encode(claims, self._segredo, algorithm="HS256"))


class VerificadorTokenServico:
    def __init__(self, segredo: str) -> None:
        self._segredo = segredo

    async def verificar(self, token: str) -> Usuario:
        try:
            claims = jwt.decode(
                token,
                self._segredo,
                algorithms=["HS256"],
                issuer=EMISSOR_INTERNO,
                leeway=TOLERANCIA_RELOGIO_SEGUNDOS,
                options={"require": ["exp", "sub", "iss"]},
            )
        except jwt.PyJWTError as erro:
            raise ErroNaoAutenticado() from erro
        if claims.get("papel") != Papel.SERVICO.value:
            raise ErroNaoAutenticado("Token interno sem papel de serviço.")
        return Usuario(
            id=str(claims["sub"]), papel=Papel.SERVICO, token=token, emissor=EMISSOR_INTERNO
        )


class VerificadorComposto:
    def __init__(self, externo: VerificadorDeToken, interno: VerificadorDeToken) -> None:
        self._externo = externo
        self._interno = interno

    async def verificar(self, token: str) -> Usuario:
        try:
            claims: Mapping[str, Any] = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as erro:
            raise ErroNaoAutenticado() from erro
        if claims.get("iss") == EMISSOR_INTERNO:
            return await self._interno.verificar(token)
        return await self._externo.verificar(token)


def criar_verificador(
    config: ConfiguracaoBase, *, cliente: httpx.AsyncClient | None = None
) -> VerificadorComposto:
    """Verificador padrão dos serviços, a partir da configuração."""
    return VerificadorComposto(
        externo=VerificadorJwks(
            config.jwks_url,
            cliente=cliente,
            ttl_segundos=config.jwks_ttl_segundos,
            claim_papel=config.jwt_claim_papel,
            emissor=config.jwt_emissor,
            audiencia=config.jwt_audiencia,
        ),
        interno=VerificadorTokenServico(config.token_servico_segredo.get_secret_value()),
    )
