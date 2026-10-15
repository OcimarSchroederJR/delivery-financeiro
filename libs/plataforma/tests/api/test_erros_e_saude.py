from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel
from structlog.testing import capture_logs

from plataforma.api.correlation import MiddlewareCorrelationId
from plataforma.api.erros import registrar_tratadores_de_erro
from plataforma.api.saude import Verificacao, criar_router_saude
from plataforma.correlation import HEADER_CORRELATION_ID
from plataforma.erros import ErroConflito


class Cartao(BaseModel):
    numero: str
    cvv: str


class Corpo(BaseModel):
    valor_centavos: int
    cartao: Cartao


async def _ok() -> None:
    return None


async def _falha() -> None:
    raise ConnectionError("banco fora")


def _app(verificacao: Verificacao = _ok) -> FastAPI:
    app = FastAPI()
    registrar_tratadores_de_erro(app)
    app.add_middleware(MiddlewareCorrelationId)
    app.include_router(criar_router_saude({"banco": verificacao}))

    @app.get("/v1/conflito")
    async def conflito() -> None:
        raise ErroConflito(
            "Pagamento recusado.", codigo="PAGAMENTO_RECUSADO", detalhes={"pagamento_id": "p1"}
        )

    @app.get("/v1/conflito-com-status")
    async def conflito_com_status() -> None:
        raise ErroConflito(
            "Pagamento recusado.",
            codigo="PAGAMENTO_RECUSADO",
            detalhes={"status": "recusado", "headers": "x", "mensagem": "ignorada"},
        )

    @app.get("/v1/quebra")
    async def quebra() -> None:
        raise RuntimeError("detalhe interno secreto")

    @app.post("/v1/corpo")
    async def corpo(_corpo: Corpo) -> dict[str, bool]:
        return {"ok": True}

    return app


async def _cliente(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transporte = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        yield cliente


@pytest.fixture
async def cliente() -> AsyncIterator[httpx.AsyncClient]:
    async for http in _cliente(_app()):
        yield http


async def test_vivo(cliente: httpx.AsyncClient) -> None:
    resposta = await cliente.get("/saude/vivo")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


async def test_pronto_ok(cliente: httpx.AsyncClient) -> None:
    resposta = await cliente.get("/saude/pronto")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok", "verificacoes": {"banco": "ok"}}


async def test_pronto_503_quando_dependencia_falha() -> None:
    async for http in _cliente(_app(_falha)):
        resposta = await http.get("/saude/pronto")
    assert resposta.status_code == 503
    corpo = resposta.json()
    assert corpo["erro"] is True
    assert corpo["codigo"] == "SERVICO_NAO_PRONTO"
    assert corpo["verificacoes"] == {"banco": "falhou"}


async def test_correlation_id_gerado_e_devolvido(cliente: httpx.AsyncClient) -> None:
    resposta = await cliente.get("/saude/vivo")
    assert resposta.headers[HEADER_CORRELATION_ID]


async def test_correlation_id_recebido_e_ecoado_no_header_e_no_erro(
    cliente: httpx.AsyncClient,
) -> None:
    resposta = await cliente.get("/v1/conflito", headers={HEADER_CORRELATION_ID: "cid-777"})
    assert resposta.headers[HEADER_CORRELATION_ID] == "cid-777"
    assert resposta.json()["correlation_id"] == "cid-777"


async def test_correlation_id_malicioso_e_substituido(cliente: httpx.AsyncClient) -> None:
    resposta = await cliente.get("/saude/vivo", headers={HEADER_CORRELATION_ID: "x" * 500})
    assert resposta.headers[HEADER_CORRELATION_ID] != "x" * 500


async def test_detalhes_com_chaves_reservadas_nao_quebram_a_resposta(
    cliente: httpx.AsyncClient,
) -> None:
    resposta = await cliente.get("/v1/conflito-com-status")
    assert resposta.status_code == 409
    corpo = resposta.json()
    assert corpo["status"] == "recusado"
    assert corpo["headers"] == "x"
    assert corpo["mensagem"] == "Pagamento recusado."
    assert corpo["codigo"] == "PAGAMENTO_RECUSADO"


async def test_erro_de_aplicacao_no_formato_padrao(cliente: httpx.AsyncClient) -> None:
    resposta = await cliente.get("/v1/conflito")
    assert resposta.status_code == 409
    corpo = resposta.json()
    assert corpo["erro"] is True
    assert corpo["mensagem"] == "Pagamento recusado."
    assert corpo["codigo"] == "PAGAMENTO_RECUSADO"
    assert corpo["pagamento_id"] == "p1"
    assert corpo["correlation_id"]


async def test_500_sem_stack_trace(cliente: httpx.AsyncClient) -> None:
    resposta = await cliente.get("/v1/quebra", headers={HEADER_CORRELATION_ID: "cid-500"})
    assert resposta.status_code == 500
    assert resposta.json() == {
        "erro": True,
        "mensagem": "Erro interno do servidor.",
        "codigo": "ERRO_INTERNO",
        "correlation_id": "cid-500",
    }
    assert "secreto" not in resposta.text
    assert resposta.headers[HEADER_CORRELATION_ID] == "cid-500"


async def test_rota_inexistente_vira_404_padrao(cliente: httpx.AsyncClient) -> None:
    resposta = await cliente.get("/nao-existe")
    assert resposta.status_code == 404
    assert resposta.json()["codigo"] == "RECURSO_NAO_ENCONTRADO"
    assert resposta.json()["erro"] is True


async def test_metodo_nao_permitido(cliente: httpx.AsyncClient) -> None:
    resposta = await cliente.delete("/saude/vivo")
    assert resposta.status_code == 405
    assert resposta.json()["codigo"] == "METODO_NAO_PERMITIDO"


async def test_validacao_422_nao_ecoa_dados_do_cartao(cliente: httpx.AsyncClient) -> None:
    resposta = await cliente.post(
        "/v1/corpo", json={"valor_centavos": "abc", "cartao": {"numero": "4111111111110000"}}
    )
    assert resposta.status_code == 422
    corpo = resposta.json()
    assert corpo["codigo"] == "REQUISICAO_INVALIDA"
    assert {item["campo"] for item in corpo["detalhes"]} == {
        "body.valor_centavos",
        "body.cartao.cvv",
    }
    assert "4111111111110000" not in resposta.text


async def test_json_malformado_vira_422_padrao(cliente: httpx.AsyncClient) -> None:
    resposta = await cliente.post(
        "/v1/corpo", content=b"{nao json", headers={"Content-Type": "application/json"}
    )
    assert resposta.status_code == 422
    assert resposta.json()["erro"] is True


async def test_requisicao_gera_log_e_saude_nao(cliente: httpx.AsyncClient) -> None:
    with capture_logs() as logs:
        await cliente.get("/saude/vivo")
        await cliente.get("/v1/conflito")
    requisicoes = [log for log in logs if log["event"] == "requisicao_http"]
    assert len(requisicoes) == 1
    assert requisicoes[0]["metodo"] == "GET"
    assert requisicoes[0]["rota"] == "/v1/conflito"
    assert requisicoes[0]["status"] == 409
