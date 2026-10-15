from typing import Any

import httpx
import pytest
import respx

from notificacoes.adaptadores.clientes.perfis import ClientePerfisHttp
from notificacoes.aplicacao.portas import Perfil, PerfilInvalido, PerfilNaoEncontrado
from plataforma.cliente_http import ClienteHttp
from plataforma.erros import ErroDependenciaIndisponivel

BASE = "http://identidade.teste"
PERFIL_JSON = {"id": "cliente-1", "nome": "Ana", "email": "cliente-1@exemplo.com", "papel": None}


class Relogio:
    def __init__(self) -> None:
        self.agora = 0.0

    def __call__(self) -> float:
        return self.agora


def _perfis(*, relogio: Relogio | None = None, credencial: str | None = None) -> ClientePerfisHttp:
    return ClientePerfisHttp(
        ClienteHttp("identidade", BASE, espera_base=0, espera_maxima=0),
        credencial=credencial,
        ttl_segundos=300.0,
        relogio=relogio or Relogio(),
    )


@respx.mock
async def test_busca_perfil_e_usa_cache_por_5_minutos() -> None:
    rota = respx.get(f"{BASE}/perfis/cliente-1").mock(
        return_value=httpx.Response(200, json=PERFIL_JSON)
    )
    relogio = Relogio()
    perfis = _perfis(relogio=relogio)
    assert await perfis.obter("cliente-1") == Perfil("cliente-1", "cliente-1@exemplo.com", "Ana")
    relogio.agora = 299.0
    await perfis.obter("cliente-1")
    assert rota.call_count == 1
    relogio.agora = 301.0
    await perfis.obter("cliente-1")
    assert rota.call_count == 2
    await perfis.fechar()


@respx.mock
async def test_envia_credencial_de_servico_so_quando_configurada() -> None:
    rota = respx.get(f"{BASE}/perfis/cliente-1").mock(
        return_value=httpx.Response(200, json=PERFIL_JSON)
    )
    await _perfis(credencial="credencial-eq1").obter("cliente-1")
    assert rota.calls.last.request.headers["Authorization"] == "Bearer credencial-eq1"
    await _perfis().obter("cliente-1")
    assert "Authorization" not in rota.calls.last.request.headers


@respx.mock
async def test_aceita_dominios_de_demonstracao() -> None:
    respx.get(f"{BASE}/perfis/loja-1").mock(
        return_value=httpx.Response(200, json={"id": "loja-1", "email": "loja@financeiro.local"})
    )
    perfil = await _perfis().obter("loja-1")
    assert (perfil.email, perfil.nome) == ("loja@financeiro.local", None)


@respx.mock
async def test_404_e_perfil_nao_encontrado() -> None:
    respx.get(f"{BASE}/perfis/ninguem").mock(return_value=httpx.Response(404))
    with pytest.raises(PerfilNaoEncontrado):
        await _perfis().obter("ninguem")


@respx.mock
@pytest.mark.parametrize(
    "corpo",
    [
        {"id": "c1"},
        {"id": "c1", "email": "sem-arroba"},
        {"id": "c1", "email": "a b@exemplo.com"},
    ],
)
async def test_perfil_sem_email_valido(corpo: dict[str, Any]) -> None:
    respx.get(f"{BASE}/perfis/c1").mock(return_value=httpx.Response(200, json=corpo))
    with pytest.raises(PerfilInvalido):
        await _perfis().obter("c1")


@respx.mock
@pytest.mark.parametrize("status", [503, 401])
async def test_identidade_fora_ou_recusando_e_erro_transitorio(status: int) -> None:
    respx.get(f"{BASE}/perfis/c1").mock(return_value=httpx.Response(status))
    with pytest.raises(ErroDependenciaIndisponivel):
        await _perfis().obter("c1")
