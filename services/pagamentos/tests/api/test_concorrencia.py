import asyncio

import httpx
import pytest

from pagamentos.testes.fakes import GatewayComBarreira
from pagamentos.testes.requisicoes import cabecalhos, corpo_pix


@pytest.fixture
def gateway() -> GatewayComBarreira:
    return GatewayComBarreira(esperadas=1)


async def test_mesma_chave_enquanto_processa_recebe_409(
    api: httpx.AsyncClient, gateway: GatewayComBarreira
) -> None:
    def enviar() -> asyncio.Future[httpx.Response]:
        return asyncio.ensure_future(
            api.post("/v1/pagamentos", json=corpo_pix(), headers=cabecalhos(chave="k-conc"))
        )

    primeira = enviar()
    await gateway.aguardar_entradas()
    segunda = await enviar()
    assert segunda.status_code == 409
    assert segunda.json()["codigo"] == "IDEMPOTENCY_EM_PROCESSAMENTO"
    gateway.liberar.set()
    concluida = await primeira
    assert concluida.status_code == 201
    repetida = await enviar()
    assert (repetida.status_code, repetida.json()) == (201, concluida.json())
