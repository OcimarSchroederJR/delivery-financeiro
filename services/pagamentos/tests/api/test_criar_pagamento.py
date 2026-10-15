from datetime import timedelta
from uuid import UUID

import httpx
import pytest
from structlog.testing import capture_logs

from pagamentos.dominio.pagamento import StatusPagamento
from pagamentos.testes.fakes import ConsultaPedidosFake, EstadoFake
from pagamentos.testes.requisicoes import (
    NUMERO_CARTAO_PREFIXO,
    TITULAR_TESTE,
    cabecalhos,
    corpo_cartao,
    corpo_pix,
)
from plataforma.correlation import HEADER_CORRELATION_ID

ROTA = "/v1/pagamentos"
ESCOPO = "POST /v1/pagamentos"


async def test_cria_pagamento_aprovado_com_cartao(
    api: httpx.AsyncClient, estado: EstadoFake
) -> None:
    resposta = await api.post(ROTA, json=corpo_cartao(), headers=cabecalhos(chave="k-1"))
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["status"] == "aprovado"
    assert (corpo["pedido_id"], corpo["cliente_id"]) == ("ped-1", "cliente-1")
    assert (corpo["valor_centavos"], corpo["metodo"], corpo["cartao_final"]) == (
        4590,
        "cartao_credito",
        "0000",
    )
    assert (corpo["valor_estornado_centavos"], corpo["saldo_estornavel_centavos"]) == (0, 4590)
    assert corpo["motivo_recusa"] is None
    assert corpo["criado_em"].endswith("Z")
    assert UUID(corpo["id"]) in estado.pagamentos
    assert [tipo for tipo, _ in estado.eventos] == ["pagamento.aprovado"]


async def test_cria_pagamento_pix(api: httpx.AsyncClient) -> None:
    resposta = await api.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave="k-pix"))
    assert resposta.status_code == 201
    assert (resposta.json()["metodo"], resposta.json()["cartao_final"]) == ("pix", None)


async def test_recusa_por_saldo_insuficiente_persiste_a_tentativa(
    api: httpx.AsyncClient, estado: EstadoFake
) -> None:
    resposta = await api.post(
        ROTA, json=corpo_cartao(final="0002"), headers=cabecalhos(chave="k-rec")
    )
    assert resposta.status_code == 409
    corpo = resposta.json()
    assert (corpo["erro"], corpo["codigo"], corpo["motivo"]) == (
        True,
        "PAGAMENTO_RECUSADO",
        "saldo_insuficiente",
    )
    assert estado.pagamentos[UUID(corpo["pagamento_id"])].status == StatusPagamento.RECUSADO
    assert [tipo for tipo, _ in estado.eventos] == ["pagamento.recusado"]


async def test_recusa_por_antifraude(api: httpx.AsyncClient) -> None:
    resposta = await api.post(ROTA, json=corpo_pix("ped-2"), headers=cabecalhos(chave="k-af"))
    assert resposta.status_code == 409
    assert resposta.json()["motivo"] == "analise_antifraude"


async def test_pedido_ja_pago(api: httpx.AsyncClient) -> None:
    await api.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave="k-a"))
    resposta = await api.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave="k-b"))
    assert resposta.status_code == 409
    assert resposta.json()["codigo"] == "PEDIDO_JA_PAGO"


async def test_pedido_inexistente(api: httpx.AsyncClient) -> None:
    resposta = await api.post(ROTA, json=corpo_pix("ped-x"), headers=cabecalhos(chave="k-x"))
    assert resposta.status_code == 422
    assert resposta.json()["codigo"] == "PEDIDO_INEXISTENTE"


async def test_pedido_de_outro_cliente(api: httpx.AsyncClient) -> None:
    resposta = await api.post(ROTA, json=corpo_pix("ped-3"), headers=cabecalhos(chave="k-o"))
    assert resposta.status_code == 403
    assert resposta.json()["codigo"] == "ACESSO_NEGADO"


async def test_admin_paga_pedido_de_qualquer_cliente(api: httpx.AsyncClient) -> None:
    resposta = await api.post(
        ROTA, json=corpo_pix("ped-3"), headers=cabecalhos("admin", "admin-1", chave="k-adm")
    )
    assert resposta.status_code == 201
    assert resposta.json()["cliente_id"] == "cliente-2"


@pytest.mark.parametrize(
    ("papel", "sub"), [("loja", "loja-1"), ("entregador", "e-1"), ("servico", "avaliacoes")]
)
async def test_papeis_sem_permissao(api: httpx.AsyncClient, papel: str, sub: str) -> None:
    resposta = await api.post(ROTA, json=corpo_pix(), headers=cabecalhos(papel, sub, chave="k"))
    assert resposta.status_code == 403


async def test_sem_token(api: httpx.AsyncClient) -> None:
    resposta = await api.post(ROTA, json=corpo_pix(), headers={"Idempotency-Key": "k"})
    assert resposta.status_code == 401
    assert resposta.json()["codigo"] == "NAO_AUTENTICADO"


async def test_sem_idempotency_key(api: httpx.AsyncClient, estado: EstadoFake) -> None:
    resposta = await api.post(ROTA, json=corpo_pix(), headers=cabecalhos())
    assert resposta.status_code == 400
    assert resposta.json()["codigo"] == "IDEMPOTENCY_KEY_AUSENTE"
    assert estado.pagamentos == {}


async def test_idempotency_key_em_branco(api: httpx.AsyncClient) -> None:
    resposta = await api.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave="   "))
    assert resposta.status_code == 400
    assert resposta.json()["codigo"] == "IDEMPOTENCY_KEY_AUSENTE"


async def test_idempotency_key_fora_do_formato(api: httpx.AsyncClient) -> None:
    resposta = await api.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave="k" * 256))
    assert resposta.status_code == 400
    assert resposta.json()["codigo"] == "IDEMPOTENCY_KEY_INVALIDA"


async def test_corpo_com_valor_e_rejeitado(api: httpx.AsyncClient) -> None:
    resposta = await api.post(
        ROTA, json={**corpo_pix(), "valor_centavos": 1}, headers=cabecalhos(chave="k-v")
    )
    assert resposta.status_code == 422
    assert resposta.json()["codigo"] == "REQUISICAO_INVALIDA"


async def test_cartao_obrigatorio_para_credito(api: httpx.AsyncClient) -> None:
    resposta = await api.post(
        ROTA,
        json={"pedido_id": "ped-1", "metodo": "cartao_credito"},
        headers=cabecalhos(chave="k-c"),
    )
    assert resposta.status_code == 422


@pytest.mark.parametrize("pedido_id", ["../admin", "ped/1", "ped%2F1", "", "p" * 65, "pedído"])
async def test_pedido_id_fora_do_padrao_422(
    api: httpx.AsyncClient, pedidos: ConsultaPedidosFake, pedido_id: str
) -> None:
    resposta = await api.post(ROTA, json=corpo_pix(pedido_id), headers=cabecalhos(chave="k-p"))
    assert resposta.status_code == 422
    assert pedidos.chamadas == []


async def test_422_nao_ecoa_numero_do_cartao(api: httpx.AsyncClient) -> None:
    resposta = await api.post(ROTA, json=corpo_cartao(cvv="12"), headers=cabecalhos(chave="k"))
    assert resposta.status_code == 422
    assert NUMERO_CARTAO_PREFIXO not in resposta.text
    assert TITULAR_TESTE not in resposta.text


async def test_eq3_fora_responde_503_e_libera_a_chave(
    api: httpx.AsyncClient, pedidos: ConsultaPedidosFake, estado: EstadoFake
) -> None:
    pedidos.fora = True
    resposta = await api.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave="k-503"))
    assert resposta.status_code == 503
    assert (resposta.json()["codigo"], resposta.json()["dependencia"]) == (
        "DEPENDENCIA_INDISPONIVEL",
        "pedidos",
    )
    assert estado.chaves == {}
    pedidos.fora = False
    repetida = await api.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave="k-503"))
    assert repetida.status_code == 201


async def test_gateway_timeout_503_sem_persistir_nada(
    api: httpx.AsyncClient, estado: EstadoFake
) -> None:
    for _ in range(2):
        resposta = await api.post(
            ROTA, json=corpo_cartao(final="0119"), headers=cabecalhos(chave="k-gw")
        )
        assert resposta.status_code == 503
        assert resposta.json()["dependencia"] == "gateway"
        assert "Idempotency-Replayed" not in resposta.headers
    assert (estado.pagamentos, estado.chaves, estado.eventos) == ({}, {}, [])


async def test_repeticao_devolve_a_mesma_resposta(
    api: httpx.AsyncClient, estado: EstadoFake
) -> None:
    primeira = await api.post(ROTA, json=corpo_cartao(), headers=cabecalhos(chave="k-rep"))
    segunda = await api.post(ROTA, json=corpo_cartao(), headers=cabecalhos(chave="k-rep"))
    assert (primeira.status_code, segunda.status_code) == (201, 201)
    assert segunda.json() == primeira.json()
    assert segunda.headers["Idempotency-Replayed"] == "true"
    assert len(estado.pagamentos) == 1
    assert len(estado.eventos) == 1


async def test_repeticao_de_recusa_devolve_o_409_gravado(
    api: httpx.AsyncClient, estado: EstadoFake
) -> None:
    corpo = corpo_cartao(final="0002")
    primeira = await api.post(ROTA, json=corpo, headers=cabecalhos(chave="k-r2"))
    segunda = await api.post(ROTA, json=corpo, headers=cabecalhos(chave="k-r2"))
    assert (primeira.status_code, segunda.status_code) == (409, 409)
    # O 1o corpo vem do tratador global de erros; o 2o, do que o apresentador gravou.
    assert segunda.json() == primeira.json()
    assert len(estado.pagamentos) == 1


async def test_mesma_chave_com_corpo_diferente(api: httpx.AsyncClient) -> None:
    await api.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave="k-dif"))
    resposta = await api.post(ROTA, json=corpo_cartao(), headers=cabecalhos(chave="k-dif"))
    assert resposta.status_code == 422
    assert resposta.json()["codigo"] == "IDEMPOTENCY_KEY_REUTILIZADA"


async def test_mesma_chave_e_corpo_de_outro_usuario_nao_recebe_a_resposta_alheia(
    api: httpx.AsyncClient,
) -> None:
    await api.post(ROTA, json=corpo_pix("ped-3"), headers=cabecalhos("admin", "a-1", chave="k-c"))
    resposta = await api.post(
        ROTA, json=corpo_pix("ped-3"), headers=cabecalhos("cliente", "cliente-2", chave="k-c")
    )
    assert resposta.status_code == 422
    assert resposta.json()["codigo"] == "IDEMPOTENCY_KEY_REUTILIZADA"


async def test_chave_expirada_processa_de_novo(api: httpx.AsyncClient, estado: EstadoFake) -> None:
    await api.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave="k-exp"))
    estado.chaves[(ESCOPO, "k-exp")].criado_em -= timedelta(hours=24, seconds=1)
    resposta = await api.post(ROTA, json=corpo_pix(), headers=cabecalhos(chave="k-exp"))
    assert resposta.status_code == 409
    assert resposta.json()["codigo"] == "PEDIDO_JA_PAGO"
    assert "Idempotency-Replayed" not in resposta.headers


async def test_correlation_id_ecoado(api: httpx.AsyncClient) -> None:
    resposta = await api.post(
        ROTA, json=corpo_pix(), headers=cabecalhos(chave="k-cid", correlation_id="cid-pag-1")
    )
    assert resposta.headers[HEADER_CORRELATION_ID] == "cid-pag-1"


async def test_logs_nunca_contem_dados_do_cartao(api: httpx.AsyncClient) -> None:
    with capture_logs() as logs:
        for pedido_id, final in (("ped-1", "0000"), ("ped-4", "0002"), ("ped-4", "0119")):
            await api.post(
                ROTA,
                json=corpo_cartao(pedido_id, final, cvv="9731"),
                headers=cabecalhos(chave=f"k-log-{final}"),
            )
    texto = repr(logs)
    assert logs
    assert NUMERO_CARTAO_PREFIXO not in texto
    assert TITULAR_TESTE not in texto
    assert "cvv" not in texto
    assert "12/28" not in texto


async def test_openapi_documenta_idempotency_key_e_erros(api: httpx.AsyncClient) -> None:
    operacao = (await api.get("/openapi.json")).json()["paths"]["/v1/pagamentos"]["post"]
    parametros = {(p["name"], p["in"]) for p in operacao["parameters"]}
    assert ("Idempotency-Key", "header") in parametros
    assert {"201", "400", "401", "403", "409", "422", "503"} <= set(operacao["responses"])
