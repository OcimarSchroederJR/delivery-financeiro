import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

import httpx
import pytest
import respx
from structlog.testing import capture_logs

from notificacoes.adaptadores.clientes.webhook import EntregadorHttpx

URL = "https://receptor.teste/hook"


@pytest.fixture
async def entregador() -> AsyncIterator[EntregadorHttpx]:
    entregador = EntregadorHttpx(timeout_segundos=5.0, permitir_rede_interna=True)
    yield entregador
    await entregador.fechar()


@respx.mock
async def test_2xx_e_sucesso_com_corpo_e_headers_intactos(entregador: EntregadorHttpx) -> None:
    rota = respx.post(URL).mock(return_value=httpx.Response(204))
    resultado = await entregador.entregar(
        URL, b'{"a":1}', {"X-Assinatura": "sha256=abc", "Content-Type": "application/json"}
    )
    assert resultado.sucesso
    assert (resultado.status_http, resultado.erro) == (204, None)
    assert resultado.duracao_ms >= 0
    enviada = rota.calls.last.request
    assert enviada.content == b'{"a":1}'
    assert enviada.headers["X-Assinatura"] == "sha256=abc"
    assert "financeiro-eq5" in enviada.headers["User-Agent"]


@respx.mock
@pytest.mark.parametrize("status", [500, 404, 302])
async def test_fora_de_2xx_e_falha_sem_seguir_redirecionamento(
    entregador: EntregadorHttpx, status: int
) -> None:
    rota = respx.post(URL).mock(
        return_value=httpx.Response(status, headers={"Location": "https://outro.teste/"})
    )
    resultado = await entregador.entregar(URL, b"{}", {})
    assert (resultado.status_http, resultado.sucesso, resultado.erro) == (status, False, None)
    assert rota.call_count == 1


@respx.mock
async def test_timeout_total_conta_como_falha() -> None:
    async def responde_devagar(_requisicao: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.5)
        return httpx.Response(200)

    respx.post(URL).mock(side_effect=responde_devagar)
    entregador = EntregadorHttpx(timeout_segundos=0.1, permitir_rede_interna=True)
    resultado = await entregador.entregar(URL, b"{}", {})
    await entregador.fechar()
    assert resultado.status_http is None
    assert resultado.erro is not None
    assert "Tempo esgotado" in resultado.erro
    assert not resultado.sucesso


@respx.mock
async def test_erro_de_rede_vira_resultado(entregador: EntregadorHttpx) -> None:
    respx.post(URL).mock(side_effect=httpx.ConnectError("recusado"))
    resultado = await entregador.entregar(URL, b"{}", {})
    assert (resultado.status_http, resultado.erro) == (None, "ConnectError")


@respx.mock
async def test_loga_antes_e_depois_sem_query_string(entregador: EntregadorHttpx) -> None:
    respx.post(host="receptor.teste", path="/hook").mock(return_value=httpx.Response(200))
    with capture_logs() as logs:
        await entregador.entregar(f"{URL}?token=abc123", b"{}", {"X-Assinatura": "sha256=xyz"})
    antes, depois = (log for log in logs if log["event"].startswith("http_saida"))
    assert (antes["event"], antes["dependencia"], antes["rota"]) == (
        "http_saida_iniciada",
        "webhook",
        "https://receptor.teste/hook",
    )
    assert (depois["event"], depois["status"]) == ("http_saida_concluida", 200)
    assert "abc123" not in str(logs)
    assert "sha256=xyz" not in str(logs)


def _resolvendo_para(*ips: str) -> Callable[[str, int], Awaitable[list[str]]]:
    async def resolver(host: str, porta: int) -> list[str]:
        assert (host, porta) == ("receptor.teste", 443)
        return list(ips)

    return resolver


@respx.mock
@pytest.mark.parametrize(
    "ips", [("10.0.0.5",), ("93.184.216.34", "127.0.0.1"), ("169.254.169.254",), ("::1",)]
)
async def test_bloqueia_destino_cujo_dns_aponta_para_rede_interna(ips: tuple[str, ...]) -> None:
    rota = respx.route().mock(return_value=httpx.Response(204))
    entregador = EntregadorHttpx(
        timeout_segundos=1.0, permitir_rede_interna=False, resolver=_resolvendo_para(*ips)
    )
    resultado = await entregador.entregar(URL, b"{}", {})
    await entregador.fechar()
    assert (resultado.status_http, resultado.sucesso) == (None, False)
    assert resultado.erro is not None
    assert "bloqueado" in resultado.erro
    assert not rota.called


@respx.mock
async def test_conecta_no_ip_validado_mantendo_host_e_sni() -> None:
    """Fixa o IP checado (sem nova resolução na conexão: evita DNS rebinding)."""
    rota = respx.post("https://93.184.216.34/hook").mock(return_value=httpx.Response(204))
    entregador = EntregadorHttpx(
        timeout_segundos=1.0,
        permitir_rede_interna=False,
        resolver=_resolvendo_para("93.184.216.34"),
    )
    resultado = await entregador.entregar(URL, b"{}", {"X-Evento-Id": "1"})
    await entregador.fechar()
    assert resultado.sucesso
    enviada = rota.calls.last.request
    assert enviada.headers["Host"] == "receptor.teste"
    assert enviada.extensions["sni_hostname"] == "receptor.teste"


@respx.mock
async def test_ip_literal_interno_e_bloqueado_sem_dns() -> None:
    async def nao_resolve(host: str, porta: int) -> list[str]:
        raise AssertionError("não devia consultar o DNS")

    entregador = EntregadorHttpx(
        timeout_segundos=1.0, permitir_rede_interna=False, resolver=nao_resolve
    )
    resultado = await entregador.entregar("https://[::ffff:127.0.0.1]/x", b"{}", {})
    await entregador.fechar()
    assert resultado.erro is not None
    assert "bloqueado" in resultado.erro


async def test_falha_de_dns_vira_resultado() -> None:
    async def falha(host: str, porta: int) -> list[str]:
        raise OSError("nome não resolvido")

    entregador = EntregadorHttpx(timeout_segundos=1.0, permitir_rede_interna=False, resolver=falha)
    resultado = await entregador.entregar(URL, b"{}", {})
    await entregador.fechar()
    assert (resultado.status_http, resultado.erro) == (None, "Falha de DNS (OSError).")
