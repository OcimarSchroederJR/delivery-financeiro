"""Avaliações conversando com o app real de Pagamentos (em memória, sem Docker)."""

from collections.abc import AsyncIterator

import httpx
import pytest
from asgi_lifespan import LifespanManager
from pydantic import SecretStr

from avaliacoes.adaptadores.clientes.pagamentos import PagamentosHttp
from avaliacoes.api import criar_app as criar_app_avaliacoes
from avaliacoes.aplicacao.portas import FabricaUnidadeDeTrabalho
from avaliacoes.aplicacao.saga import PoliticaDeRetentativa
from avaliacoes.composicao import Dependencias
from avaliacoes.config import Config
from avaliacoes.testes.fakes import PedidosFake, RelogioFake
from pagamentos.adaptadores.clientes.gateway_simulado import GatewaySimulado
from pagamentos.api import Substituicoes
from pagamentos.api import criar_app as criar_app_pagamentos
from pagamentos.config import Config as ConfigPagamentos
from pagamentos.dominio.pedido import Pedido
from pagamentos.testes.fakes import ConsultaPedidosFake, EstadoFake, fabrica_fake
from pagamentos.testes.requisicoes import GERADOR, cabecalhos, corpo_pix, verificador_de_teste
from plataforma.auth import EmissorTokenServico
from plataforma.cliente_http import ClienteHttp
from plataforma.testes.tokens import SEGREDO_SERVICO_TESTE, criar_verificador_de_teste

INFRA_INEXISTENTE = {
    "database_url": "postgresql+asyncpg://x:x@127.0.0.1:1/x",
    "rabbitmq_url": "amqp://guest:guest@127.0.0.1:1/",
}


@pytest.fixture
async def pagamentos_api() -> AsyncIterator[httpx.ASGITransport]:
    pedidos = ConsultaPedidosFake()
    pedidos.adicionar(Pedido("ped-9", "cliente-1", 5000, "entregue"))
    app = criar_app_pagamentos(
        ConfigPagamentos(
            token_servico_segredo=SecretStr(SEGREDO_SERVICO_TESTE),
            ambiente="teste",
            **INFRA_INEXISTENTE,
        ),
        Substituicoes(
            verificador=verificador_de_teste(),
            pedidos=pedidos,
            gateway=GatewaySimulado(),
            fabrica_uow=fabrica_fake(EstadoFake()),
        ),
    )
    async with LifespanManager(app) as gerenciador:
        yield httpx.ASGITransport(app=gerenciador.app, raise_app_exceptions=False)


@pytest.fixture
async def http(
    pagamentos_api: httpx.ASGITransport,
    config: Config,
    uow: FabricaUnidadeDeTrabalho,
    relogio: RelogioFake,
) -> AsyncIterator[tuple[httpx.AsyncClient, httpx.AsyncClient]]:
    async with ClienteHttp(
        "pagamentos", "http://pagamentos", transporte=pagamentos_api, espera_base=0
    ) as cliente_pagamentos:
        dependencias = Dependencias(
            uow=uow,
            pedidos=PedidosFake(),
            pagamentos=PagamentosHttp(cliente_pagamentos),
            emissor_token=EmissorTokenServico(SEGREDO_SERVICO_TESTE, servico="avaliacoes"),
            politica=PoliticaDeRetentativa(),
            relogio=relogio,
        )
        app = criar_app_avaliacoes(
            config, verificador=criar_verificador_de_teste(GERADOR), dependencias=dependencias
        )
        async with (
            LifespanManager(app) as gerenciador,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=gerenciador.app, raise_app_exceptions=False),
                base_url="http://avaliacoes",
            ) as avaliacoes,
            httpx.AsyncClient(transport=pagamentos_api, base_url="http://pagamentos") as pagamentos,
        ):
            yield avaliacoes, pagamentos


async def test_disputa_sobre_pagamento_parcialmente_estornado_usa_o_saldo(
    http: tuple[httpx.AsyncClient, httpx.AsyncClient],
) -> None:
    avaliacoes, pagamentos = http
    pago = await pagamentos.post(
        "/v1/pagamentos", json=corpo_pix("ped-9"), headers=cabecalhos(chave="pag-ped-9")
    )
    assert (pago.status_code, pago.json()["valor_centavos"]) == (201, 5000)
    estorno = await pagamentos.post(
        f"/v1/pagamentos/{pago.json()['id']}/estornos",
        json={"valor_centavos": 3000, "motivo": "item faltando"},
        headers=cabecalhos("admin", "admin-1", chave="estorno-1"),
    )
    assert estorno.status_code == 201

    def disputa(valor: int) -> dict[str, object]:
        return {"pedido_id": "ped-9", "motivo": "item_faltando", "valor_solicitado_centavos": valor}

    recusada = await avaliacoes.post("/v1/disputas", json=disputa(3000), headers=cabecalhos())
    assert (recusada.status_code, recusada.json()["codigo"]) == (422, "VALOR_EXCEDE_PAGO")

    aberta = await avaliacoes.post("/v1/disputas", json=disputa(2000), headers=cabecalhos())
    assert aberta.status_code == 201
    decidida = await avaliacoes.patch(
        f"/v1/disputas/{aberta.json()['id']}",
        json={"status": "procedente"},
        headers=cabecalhos("admin", "admin-1"),
    )
    assert decidida.json()["status"] == "resolvida"
    final = await pagamentos.get(
        f"/v1/pagamentos/{pago.json()['id']}", headers=cabecalhos("admin", "admin-1")
    )
    assert (final.json()["status"], final.json()["saldo_estornavel_centavos"]) == ("estornado", 0)
