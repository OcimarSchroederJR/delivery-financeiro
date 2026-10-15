import httpx
from pydantic import SecretStr

from pagamentos.api import criar_app
from pagamentos.config import Config
from plataforma.correlation import HEADER_CORRELATION_ID
from plataforma.testes.tokens import SEGREDO_SERVICO_TESTE


async def test_vivo(cliente: httpx.AsyncClient) -> None:
    resposta = await cliente.get("/saude/vivo")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}
    assert resposta.headers[HEADER_CORRELATION_ID]


async def test_pronto_sem_banco_e_broker_responde_503(cliente: httpx.AsyncClient) -> None:
    resposta = await cliente.get("/saude/pronto")
    assert resposta.status_code == 503
    corpo = resposta.json()
    assert corpo["erro"] is True
    assert corpo["verificacoes"] == {"banco": "falhou", "broker": "falhou"}


async def test_openapi_publicado(cliente: httpx.AsyncClient) -> None:
    resposta = await cliente.get("/openapi.json")
    assert resposta.status_code == 200
    assert resposta.json()["info"]["title"] == "Pagamentos"


async def test_rota_desconhecida_no_formato_de_erro(cliente: httpx.AsyncClient) -> None:
    resposta = await cliente.get("/v1/nao-existe")
    assert resposta.status_code == 404
    assert resposta.json()["erro"] is True


def test_root_path_vem_da_config() -> None:
    config = Config(token_servico_segredo=SecretStr(SEGREDO_SERVICO_TESTE), root_path="/pagamentos")
    assert criar_app(config).root_path == "/pagamentos"
