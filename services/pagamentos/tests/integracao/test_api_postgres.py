import asyncio
from collections.abc import AsyncIterator, Mapping
from typing import Any, Self

import httpx
import pytest
from asgi_lifespan import LifespanManager
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from pagamentos.adaptadores.clientes.gateway_simulado import GatewaySimulado
from pagamentos.adaptadores.db.modelos import MensagemOutbox
from pagamentos.adaptadores.db.unidade_de_trabalho import UnidadeDeTrabalhoSql
from pagamentos.api import Substituicoes, criar_app
from pagamentos.aplicacao.portas import GatewayDePagamento
from pagamentos.config import Config
from pagamentos.testes.fakes import ConsultaPedidosFake, GatewayComBarreira
from pagamentos.testes.requisicoes import (
    NUMERO_CARTAO_PREFIXO,
    TITULAR_TESTE,
    cabecalhos,
    corpo_cartao,
    corpo_pix,
    verificador_de_teste,
)
from plataforma.db import criar_engine, criar_fabrica_sessoes
from plataforma.erros import ErroDependenciaIndisponivel
from plataforma.testes.tokens import SEGREDO_SERVICO_TESTE

pytestmark = pytest.mark.integracao

ROTA = "/v1/pagamentos"


@pytest.fixture
def gateway(request: pytest.FixtureRequest) -> GatewayDePagamento:
    """Sem parâmetro: gateway simulado. Com ``indirect=True``: barreira com N entradas."""
    esperadas = getattr(request, "param", None)
    return GatewaySimulado() if esperadas is None else GatewayComBarreira(esperadas)


@pytest.fixture
async def api_real(
    banco_migrado: str, gateway: GatewayDePagamento
) -> AsyncIterator[httpx.AsyncClient]:
    config = Config(
        token_servico_segredo=SecretStr(SEGREDO_SERVICO_TESTE),
        ambiente="teste",
        database_url=banco_migrado,
        rabbitmq_url="amqp://guest:guest@127.0.0.1:1/",
    )
    substituicoes = Substituicoes(
        verificador=verificador_de_teste(), pedidos=ConsultaPedidosFake(), gateway=gateway
    )
    async with LifespanManager(criar_app(config, substituicoes)) as gerenciador:
        transporte = httpx.ASGITransport(app=gerenciador.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as http:
            yield http


async def _escalar(url: str, sql: str) -> Any:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conexao:
            return (await conexao.execute(text(sql))).scalar_one()
    finally:
        await engine.dispose()


async def _outbox(url: str) -> list[dict[str, Any]]:
    engine = criar_engine(url)
    try:
        async with criar_fabrica_sessoes(engine)() as sessao:
            registros = (
                await sessao.scalars(select(MensagemOutbox).order_by(MensagemOutbox.id))
            ).all()
            return [registro.envelope for registro in registros]
    finally:
        await engine.dispose()


async def test_fluxo_completo_grava_outbox_com_correlation_id(
    api_real: httpx.AsyncClient, banco_migrado: str
) -> None:
    criado = await api_real.post(
        ROTA, json=corpo_cartao(), headers=cabecalhos(chave="k-e2e", correlation_id="cid-e2e")
    )
    assert criado.status_code == 201
    pagamento_id = criado.json()["id"]
    estorno = await api_real.post(
        f"{ROTA}/{pagamento_id}/estornos",
        json={"valor_centavos": 1000, "motivo": "item faltando"},
        headers=cabecalhos("servico", "avaliacoes", chave="disputa-e2e"),
    )
    assert estorno.status_code == 201
    detalhe = (await api_real.get(f"{ROTA}/{pagamento_id}", headers=cabecalhos())).json()
    assert (detalhe["status"], detalhe["saldo_estornavel_centavos"]) == (
        "parcialmente_estornado",
        3590,
    )
    envelopes = await _outbox(banco_migrado)
    assert [e["tipo"] for e in envelopes] == ["pagamento.aprovado", "pagamento.estornado"]
    assert envelopes[0]["correlation_id"] == "cid-e2e"
    assert envelopes[0]["dados"] == {
        "pagamento_id": pagamento_id,
        "pedido_id": "ped-1",
        "cliente_id": "cliente-1",
        "valor_centavos": 4590,
        "metodo": "cartao_credito",
    }
    assert envelopes[1]["dados"]["estorno_id"] == estorno.json()["id"]


async def test_cartao_nunca_e_persistido(api_real: httpx.AsyncClient, banco_migrado: str) -> None:
    await api_real.post(ROTA, json=corpo_cartao("ped-1", "0000"), headers=cabecalhos(chave="c-1"))
    await api_real.post(ROTA, json=corpo_cartao("ped-4", "0002"), headers=cabecalhos(chave="c-2"))
    textos = []
    for tabela in ("pagamentos", "estornos", "chaves_idempotencia", "outbox"):
        textos.append(
            await _escalar(
                banco_migrado,
                f"SELECT coalesce(string_agg(row_to_json(t)::text, ' '), '') FROM {tabela} t",  # noqa: S608
            )
        )
    tudo = " ".join(textos)
    assert '"cartao_final":"0000"' in tudo
    assert NUMERO_CARTAO_PREFIXO not in tudo
    assert TITULAR_TESTE not in tudo
    assert "12/28" not in tudo
    assert "cvv" not in tudo


async def test_repeticao_com_a_mesma_chave(api_real: httpx.AsyncClient, banco_migrado: str) -> None:
    primeira = await api_real.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave="k-rep"))
    segunda = await api_real.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave="k-rep"))
    assert segunda.json() == primeira.json()
    assert segunda.headers["Idempotency-Replayed"] == "true"
    assert await _escalar(banco_migrado, "SELECT count(*) FROM pagamentos") == 1
    assert await _escalar(banco_migrado, "SELECT count(*) FROM outbox") == 1


@pytest.mark.parametrize("gateway", [1], indirect=True)
async def test_mesma_chave_em_paralelo(
    api_real: httpx.AsyncClient, gateway: GatewayComBarreira, banco_migrado: str
) -> None:
    primeira = asyncio.ensure_future(
        api_real.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave="k-par"))
    )
    await gateway.aguardar_entradas()
    segunda = await api_real.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave="k-par"))
    assert segunda.status_code == 409
    assert segunda.json()["codigo"] == "IDEMPOTENCY_EM_PROCESSAMENTO"
    gateway.liberar.set()
    assert (await primeira).status_code == 201
    assert await _escalar(banco_migrado, "SELECT count(*) FROM pagamentos") == 1


@pytest.mark.parametrize("gateway", [2], indirect=True)
async def test_chaves_diferentes_mesmo_pedido_em_paralelo(
    api_real: httpx.AsyncClient, gateway: GatewayComBarreira, banco_migrado: str
) -> None:
    tarefas = [
        asyncio.ensure_future(
            api_real.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave=chave))
        )
        for chave in ("k-a", "k-b")
    ]
    await gateway.aguardar_entradas()
    gateway.liberar.set()
    respostas = await asyncio.gather(*tarefas)
    assert sorted(r.status_code for r in respostas) == [201, 409]
    perdedora = next(r for r in respostas if r.status_code == 409)
    assert perdedora.json()["codigo"] == "PEDIDO_JA_PAGO"
    assert (
        await _escalar(banco_migrado, "SELECT count(*) FROM pagamentos WHERE status <> 'recusado'")
        == 1
    )


async def test_estornos_simultaneos_nao_passam_do_saldo(
    api_real: httpx.AsyncClient, banco_migrado: str
) -> None:
    pagamento_id = (
        await api_real.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave="k-est"))
    ).json()["id"]
    respostas = await asyncio.gather(
        *(
            api_real.post(
                f"{ROTA}/{pagamento_id}/estornos",
                json={"motivo": "saldo inteiro"},
                headers=cabecalhos("admin", "admin-1", chave=chave),
            )
            for chave in ("e-1", "e-2")
        )
    )
    assert sorted(r.status_code for r in respostas) == [201, 409]
    assert await _escalar(banco_migrado, "SELECT sum(valor_centavos) FROM estornos") == 4590


async def test_gateway_timeout_nao_deixa_rastro_no_banco(
    api_real: httpx.AsyncClient, banco_migrado: str
) -> None:
    resposta = await api_real.post(
        ROTA, json=corpo_cartao(final="0119"), headers=cabecalhos(chave="k-to")
    )
    assert resposta.status_code == 503
    for tabela in ("pagamentos", "chaves_idempotencia", "outbox"):
        assert await _escalar(banco_migrado, f"SELECT count(*) FROM {tabela}") == 0  # noqa: S608


async def test_estorno_repetido_pela_saga_no_banco_real(
    api_real: httpx.AsyncClient, banco_migrado: str
) -> None:
    pagamento_id = (
        await api_real.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave="k-saga"))
    ).json()["id"]
    corpo = {"valor_centavos": 1000, "motivo": "disputa procedente"}
    servico = cabecalhos("servico", "avaliacoes", chave="disputa-42")
    rota = f"{ROTA}/{pagamento_id}/estornos"
    primeira = await api_real.post(rota, json=corpo, headers=servico)
    segunda = await api_real.post(rota, json=corpo, headers=servico)
    assert primeira.json()["id"] == segunda.json()["id"]
    assert await _escalar(banco_migrado, "SELECT count(*) FROM estornos") == 1
    assert (
        await _escalar(
            banco_migrado, "SELECT count(*) FROM outbox WHERE tipo = 'pagamento.estornado'"
        )
        == 1
    )


class _UnidadeQueFalhaDepoisDoCommitDoEstorno(UnidadeDeTrabalhoSql):
    """Simula uma falha (ex.: serialização ou publicação) logo depois do commit do estorno."""

    falhas_restantes = 1

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        self.tipos_registrados: list[str] = []
        registrar = self.eventos.registrar

        def registrar_e_anotar(tipo: str, dados: Mapping[str, Any]) -> None:
            self.tipos_registrados.append(tipo)
            registrar(tipo, dados)

        self.eventos.registrar = registrar_e_anotar  # type: ignore[method-assign]
        return self

    async def commit(self) -> None:
        await super().commit()
        classe = _UnidadeQueFalhaDepoisDoCommitDoEstorno
        if "pagamento.estornado" in self.tipos_registrados and classe.falhas_restantes > 0:
            classe.falhas_restantes -= 1
            raise ErroDependenciaIndisponivel("broker")


async def test_falha_depois_do_commit_do_estorno_nao_estorna_de_novo(banco_migrado: str) -> None:
    engine = criar_engine(banco_migrado)
    fabrica_sessoes = criar_fabrica_sessoes(engine)
    _UnidadeQueFalhaDepoisDoCommitDoEstorno.falhas_restantes = 1
    config = Config(
        token_servico_segredo=SecretStr(SEGREDO_SERVICO_TESTE),
        ambiente="teste",
        database_url=banco_migrado,
        rabbitmq_url="amqp://guest:guest@127.0.0.1:1/",
    )
    substituicoes = Substituicoes(
        verificador=verificador_de_teste(),
        pedidos=ConsultaPedidosFake(),
        gateway=GatewaySimulado(),
        fabrica_uow=lambda: _UnidadeQueFalhaDepoisDoCommitDoEstorno(fabrica_sessoes),
    )
    try:
        async with LifespanManager(criar_app(config, substituicoes)) as gerenciador:
            transporte = httpx.ASGITransport(app=gerenciador.app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as http:
                pagamento_id = (
                    await http.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave="k-pos"))
                ).json()["id"]
                rota = f"{ROTA}/{pagamento_id}/estornos"
                corpo = {"valor_centavos": 1000, "motivo": "disputa procedente"}
                servico = cabecalhos("servico", "avaliacoes", chave="disputa-pos-commit")
                primeira = await http.post(rota, json=corpo, headers=servico)
                segunda = await http.post(rota, json=corpo, headers=servico)
    finally:
        await engine.dispose()
    assert primeira.status_code == 503
    assert segunda.status_code == 201
    assert segunda.headers["Idempotency-Replayed"] == "true"
    assert segunda.json()["valor_centavos"] == 1000
    assert await _escalar(banco_migrado, "SELECT count(*) FROM estornos") == 1
    assert (
        await _escalar(
            banco_migrado, "SELECT count(*) FROM outbox WHERE tipo = 'pagamento.estornado'"
        )
        == 1
    )
