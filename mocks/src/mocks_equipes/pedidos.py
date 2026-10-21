"""Mock da Equipe 3 (Pedidos): pedidos com estado controlável."""

from enum import StrEnum

from fastapi import FastAPI, Response, status
from pydantic import BaseModel, Field

from mocks_equipes.comum import criar_app_mock, router_com_falhas
from plataforma.erros import ErroNaoEncontrado
from plataforma.tempo import DataHoraUTC, agora_utc


class StatusPedido(StrEnum):
    CRIADO = "criado"
    CONFIRMADO = "confirmado"
    EM_PREPARO = "em_preparo"
    SAIU_PARA_ENTREGA = "saiu_para_entrega"
    ENTREGUE = "entregue"
    CANCELADO = "cancelado"


class DadosPedido(BaseModel):
    cliente_id: str = Field(min_length=1)
    restaurante_id: str = Field(min_length=1)
    valor_total_centavos: int = Field(ge=0)
    status: StatusPedido = StatusPedido.CONFIRMADO


class Pedido(DadosPedido):
    id: str
    criado_em: DataHoraUTC


class AlteracaoDeStatus(BaseModel):
    status: StatusPedido


SEMENTE: dict[str, DadosPedido] = {
    "ped-1": DadosPedido(
        cliente_id="cliente-1", restaurante_id="rest-1", valor_total_centavos=4590
    ),
    "ped-2": DadosPedido(
        cliente_id="cliente-1", restaurante_id="rest-1", valor_total_centavos=600_000
    ),
    "ped-3": DadosPedido(
        cliente_id="cliente-2",
        restaurante_id="rest-2",
        valor_total_centavos=2590,
        status=StatusPedido.ENTREGUE,
    ),
    "ped-4": DadosPedido(
        cliente_id="cliente-1",
        restaurante_id="rest-1",
        valor_total_centavos=3200,
        status=StatusPedido.ENTREGUE,
    ),
}


def criar_app() -> FastAPI:
    app = criar_app_mock(
        "mock-pedidos",
        "Mock Pedidos (Eq. 3)",
        "Pedidos em memória com cliente, restaurante, valor em centavos e status.",
    )
    pedidos: dict[str, Pedido] = {
        pedido_id: Pedido(id=pedido_id, criado_em=agora_utc(), **dados.model_dump())
        for pedido_id, dados in SEMENTE.items()
    }
    rotas = router_com_falhas()

    def _buscar(pedido_id: str) -> Pedido:
        if pedido_id not in pedidos:
            raise ErroNaoEncontrado("Pedido não encontrado.", codigo="PEDIDO_NAO_ENCONTRADO")
        return pedidos[pedido_id]

    @rotas.get("/pedidos", response_model=list[Pedido])
    async def listar() -> list[Pedido]:
        return list(pedidos.values())

    @rotas.get("/pedidos/{pedido_id}", response_model=Pedido)
    async def obter(pedido_id: str) -> Pedido:
        return _buscar(pedido_id)

    @rotas.put("/pedidos/{pedido_id}", response_model=Pedido)
    async def criar_ou_substituir(pedido_id: str, dados: DadosPedido, resposta: Response) -> Pedido:
        resposta.status_code = (
            status.HTTP_200_OK if pedido_id in pedidos else status.HTTP_201_CREATED
        )
        pedidos[pedido_id] = Pedido(id=pedido_id, criado_em=agora_utc(), **dados.model_dump())
        return pedidos[pedido_id]

    @rotas.patch("/pedidos/{pedido_id}", response_model=Pedido)
    async def alterar_status(pedido_id: str, alteracao: AlteracaoDeStatus) -> Pedido:
        pedidos[pedido_id] = _buscar(pedido_id).model_copy(update={"status": alteracao.status})
        return pedidos[pedido_id]

    app.include_router(rotas)
    return app


app = criar_app()
