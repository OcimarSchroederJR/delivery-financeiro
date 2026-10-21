import httpx
from asgi_lifespan import LifespanManager

from pagamentos.api import Substituicoes, criar_app
from pagamentos.config import Config
from pagamentos.testes.fakes import EstadoFake, fabrica_fake
from pagamentos.testes.requisicoes import cabecalhos, corpo_pix, verificador_de_teste


async def test_api_consulta_a_eq3_com_o_token_do_usuario(config: Config) -> None:
    recebidas: list[httpx.Request] = []

    def eq3(requisicao: httpx.Request) -> httpx.Response:
        recebidas.append(requisicao)
        return httpx.Response(
            200,
            json={
                "id": "ped-9",
                "cliente_id": "cliente-1",
                "valor_total_centavos": 1234,
                "status": "confirmado",
            },
        )

    app = criar_app(
        config,
        Substituicoes(
            verificador=verificador_de_teste(),
            transporte_pedidos=httpx.MockTransport(eq3),
            fabrica_uow=fabrica_fake(EstadoFake()),
        ),
    )
    headers = cabecalhos(chave="k-eq3")
    async with LifespanManager(app) as gerenciador:
        transporte = httpx.ASGITransport(app=gerenciador.app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://teste") as http:
            resposta = await http.post("/v1/pagamentos", json=corpo_pix("ped-9"), headers=headers)
    assert resposta.status_code == 201
    assert resposta.json()["valor_centavos"] == 1234
    assert recebidas[0].url.path == "/pedidos/ped-9"
    assert recebidas[0].headers["Authorization"] == headers["Authorization"]
