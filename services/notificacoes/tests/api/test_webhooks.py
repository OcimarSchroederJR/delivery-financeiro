import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

import httpx
from asgi_lifespan import LifespanManager
from pydantic import SecretStr

from notificacoes.adaptadores.memoria import ArmazenamentoEmMemoria, fabrica_em_memoria
from notificacoes.api import criar_app
from notificacoes.config import Config
from notificacoes.dominio.entrega import EntregaWebhook
from plataforma.auth import EmissorTokenServico
from plataforma.testes.tokens import (
    SEGREDO_SERVICO_TESTE,
    GeradorDeTokens,
    criar_verificador_de_teste,
)

Bearer = Callable[[str, str], dict[str, str]]
NOVA = {"url": "http://localhost:9099/hook", "eventos": ["pagamento.*"]}


async def _criar(api: httpx.AsyncClient, cabecalhos: dict[str, str]) -> dict[str, object]:
    resposta = await api.post("/v1/webhooks", json=NOVA, headers=cabecalhos)
    assert resposta.status_code == 201
    corpo: dict[str, object] = resposta.json()
    return corpo


async def test_listagem_nao_traz_segredo(api: httpx.AsyncClient, bearer: Bearer) -> None:
    cabecalhos = bearer("cliente-1", "cliente")
    criada = await _criar(api, cabecalhos)
    assert isinstance(criada["segredo"], str)
    assert len(criada["segredo"]) >= 40
    assert (criada["criado_por"], criada["somente_proprios"], criada["ativa"]) == (
        "cliente-1",
        True,
        True,
    )
    assert str(criada["criado_em"]).endswith("Z")
    lista = (await api.get("/v1/webhooks", headers=cabecalhos)).json()
    assert [item["id"] for item in lista["itens"]] == [criada["id"]]
    assert "segredo" not in lista["itens"][0]


async def test_url_e_padroes_invalidos_422(api: httpx.AsyncClient, bearer: Bearer) -> None:
    cabecalhos = bearer("cliente-1", "cliente")
    casos = [
        ({"url": "ftp://x.com/h", "eventos": ["pagamento.*"]}, "URL_DE_WEBHOOK_INVALIDA"),
        ({"url": "https://x.com/h", "eventos": ["Pagamento"]}, "PADRAO_DE_EVENTO_INVALIDO"),
        ({"url": "https://x.com/h", "eventos": []}, "REQUISICAO_INVALIDA"),
        ({**NOVA, "segredo": "escolhido-pelo-cliente"}, "REQUISICAO_INVALIDA"),
    ]
    for corpo, codigo in casos:
        resposta = await api.post("/v1/webhooks", json=corpo, headers=cabecalhos)
        assert (resposta.status_code, resposta.json()["codigo"]) == (422, codigo)


async def test_listagem_por_dono_admin_e_paginacao(api: httpx.AsyncClient, bearer: Bearer) -> None:
    for sub in ("cliente-1", "cliente-1", "cliente-2"):
        await _criar(api, bearer(sub, "cliente"))
    do_cliente = (await api.get("/v1/webhooks", headers=bearer("cliente-1", "cliente"))).json()
    assert do_cliente["total"] == 2
    do_admin = (await api.get("/v1/webhooks?tamanho=1", headers=bearer("admin-1", "admin"))).json()
    assert (len(do_admin["itens"]), do_admin["total"], do_admin["pagina"]) == (1, 3, 1)


async def test_remover_webhook(api: httpx.AsyncClient, bearer: Bearer) -> None:
    dono = bearer("cliente-1", "cliente")
    criada = await _criar(api, dono)
    rota = f"/v1/webhooks/{criada['id']}"
    assert (await api.delete(rota, headers=bearer("cliente-2", "cliente"))).status_code == 403
    removida = await api.delete(rota, headers=dono)
    assert (removida.status_code, removida.content) == (204, b"")
    de_novo = await api.delete(rota, headers=dono)
    assert (de_novo.status_code, de_novo.json()["codigo"]) == (404, "ASSINATURA_NAO_ENCONTRADA")
    assert (await api.delete("/v1/webhooks/nao-uuid", headers=dono)).status_code == 422


async def test_entregas_paginadas_e_protegidas(
    api: httpx.AsyncClient, bearer: Bearer, armazenamento: ArmazenamentoEmMemoria
) -> None:
    dono = bearer("cliente-1", "cliente")
    criada = await _criar(api, dono)
    for tentativa in (1, 2, 3):
        armazenamento.entregas.append(
            EntregaWebhook.registrar(
                assinatura_id=uuid.UUID(str(criada["id"])),
                mensagem_id=uuid.uuid4(),
                tentativa=tentativa,
                status_http=500 if tentativa < 3 else 204,
                duracao_ms=12,
                erro=None,
                agora=datetime(2026, 10, 14, 14, 30, tentativa, tzinfo=UTC),
            )
        )
    rota = f"/v1/webhooks/{criada['id']}/entregas"
    pagina = (await api.get(f"{rota}?tamanho=2", headers=dono)).json()
    assert (len(pagina["itens"]), pagina["total"]) == (2, 3)
    assert pagina["itens"][0]["status_http"] == 204
    assert set(pagina["itens"][0]) == {
        "id",
        "assinatura_id",
        "mensagem_id",
        "tentativa",
        "status_http",
        "duracao_ms",
        "erro",
        "criado_em",
    }
    assert (await api.get(rota, headers=bearer("cliente-2", "cliente"))).status_code == 403
    inexistente = f"/v1/webhooks/{uuid.uuid4()}/entregas"
    assert (await api.get(inexistente, headers=dono)).status_code == 404


async def test_token_de_servico_nao_gere_webhooks(api: httpx.AsyncClient) -> None:
    token = EmissorTokenServico(SEGREDO_SERVICO_TESTE, servico="avaliacoes").emitir()
    resposta = await api.post(
        "/v1/webhooks", json=NOVA, headers={"Authorization": f"Bearer {token}"}
    )
    assert resposta.status_code == 403


async def _api_de_producao(gerador: GeradorDeTokens) -> AsyncIterator[httpx.AsyncClient]:
    config = Config(
        token_servico_segredo=SecretStr(SEGREDO_SERVICO_TESTE),
        ambiente="producao",
        webhook_segredo_cifragem=SecretStr("c" * 32),
        database_url="postgresql+asyncpg://x:x@127.0.0.1:1/x",
        rabbitmq_url="amqp://guest:guest@127.0.0.1:1/",
    )
    app = criar_app(
        config,
        fabrica_uow=fabrica_em_memoria(ArmazenamentoEmMemoria()),
        verificador=criar_verificador_de_teste(gerador),
    )
    async with LifespanManager(app) as gerenciador:
        transporte = httpx.ASGITransport(app=gerenciador.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as http:
            yield http


async def test_https_obrigatorio_em_producao() -> None:
    gerador = GeradorDeTokens()
    cabecalhos = {"Authorization": f"Bearer {gerador.emitir('cliente-1', 'cliente')}"}
    async for api in _api_de_producao(gerador):
        resposta = await api.post("/v1/webhooks", json=NOVA, headers=cabecalhos)
        assert (resposta.status_code, resposta.json()["codigo"]) == (422, "URL_DE_WEBHOOK_INVALIDA")
        aceita = await api.post(
            "/v1/webhooks",
            json={**NOVA, "url": "https://receptor.exemplo.com/hook"},
            headers=cabecalhos,
        )
        assert aceita.status_code == 201
