"""Cliente de ``GET {IDENTIDADE_URL}/perfis/{id}`` (Eq. 1) com cache de 5 min.

Usa o ``ClienteHttp`` da plataforma (timeout 1 s/3 s, 3 tentativas em GET,
circuit breaker, logs ``http_saida_*``). 404 é definitivo; 5xx, timeout,
circuito aberto e respostas inesperadas (ex.: 401 por credencial errada) são
transitórios e fazem a tarefa de e-mail ir para a fila de retry.
"""

import re
import time
from collections.abc import Callable
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, ValidationError

from notificacoes.aplicacao.portas import Perfil, PerfilInvalido, PerfilNaoEncontrado
from plataforma.cliente_http import ClienteHttp
from plataforma.erros import ErroDependenciaIndisponivel

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class _PerfilResposta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    email: str
    nome: str | None = None


class ClientePerfisHttp:
    """Implementa ``ClientePerfis``."""

    def __init__(
        self,
        http: ClienteHttp,
        *,
        credencial: str | None = None,
        ttl_segundos: float = 300.0,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._credencial = credencial
        self._ttl = ttl_segundos
        self._relogio = relogio
        self._cache: dict[str, tuple[float, Perfil]] = {}

    async def obter(self, usuario_id: str) -> Perfil:
        agora = self._relogio()
        em_cache = self._cache.get(usuario_id)
        if em_cache is not None and em_cache[0] > agora:
            return em_cache[1]
        resposta = await self._http.get(
            f"/perfis/{quote(usuario_id, safe='')}", token=self._credencial
        )
        if resposta.status_code == 404:
            raise PerfilNaoEncontrado(f"Perfil {usuario_id} não existe na Identidade.")
        if resposta.status_code != 200:
            raise ErroDependenciaIndisponivel(
                self._http.dependencia,
                f"Resposta inesperada da Identidade: HTTP {resposta.status_code}.",
            )
        try:
            dados = _PerfilResposta.model_validate_json(resposta.content)
        except ValidationError as erro:
            raise PerfilInvalido(f"Perfil {usuario_id} sem e-mail.") from erro
        if not _EMAIL.fullmatch(dados.email):
            raise PerfilInvalido(f"Perfil {usuario_id} com e-mail inválido.")
        perfil = Perfil(id=dados.id, email=dados.email, nome=dados.nome)
        self._cache[usuario_id] = (agora + self._ttl, perfil)
        return perfil

    async def fechar(self) -> None:
        await self._http.fechar()
