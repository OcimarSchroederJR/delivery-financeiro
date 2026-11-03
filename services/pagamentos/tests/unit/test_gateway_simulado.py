import time

import pytest

from pagamentos.adaptadores.clientes.gateway_simulado import GatewaySimulado
from pagamentos.aplicacao.portas import ResultadoAutorizacao
from pagamentos.dominio.cartao import DadosCartao
from pagamentos.dominio.pagamento import MetodoPagamento
from plataforma.erros import ErroDependenciaIndisponivel


def _cartao(final: str) -> DadosCartao:
    return DadosCartao(numero="411111111111" + final, titular="Fulano", validade="12/28", cvv="123")


@pytest.mark.parametrize(
    ("final", "esperado"),
    [
        ("0000", ResultadoAutorizacao(aprovado=True)),
        ("1234", ResultadoAutorizacao(aprovado=True)),
        ("0002", ResultadoAutorizacao(aprovado=False, motivo_recusa="saldo_insuficiente")),
    ],
)
async def test_decide_pelos_ultimos_digitos(final: str, esperado: ResultadoAutorizacao) -> None:
    resultado = await GatewaySimulado().autorizar(
        metodo=MetodoPagamento.CARTAO_CREDITO, valor_centavos=4590, cartao=_cartao(final)
    )
    assert resultado == esperado


async def test_pix_sempre_aprovado() -> None:
    resultado = await GatewaySimulado().autorizar(
        metodo=MetodoPagamento.PIX, valor_centavos=4590, cartao=None
    )
    assert resultado == ResultadoAutorizacao(aprovado=True)


async def test_final_0119_e_timeout_tratado_como_503() -> None:
    with pytest.raises(ErroDependenciaIndisponivel) as erro:
        await GatewaySimulado().autorizar(
            metodo=MetodoPagamento.CARTAO_CREDITO, valor_centavos=4590, cartao=_cartao("0119")
        )
    assert erro.value.status_http == 503
    assert erro.value.dependencia == "gateway"


async def test_timeout_espera_o_atraso_configurado() -> None:
    inicio = time.perf_counter()
    with pytest.raises(ErroDependenciaIndisponivel):
        await GatewaySimulado(atraso_timeout=0.05).autorizar(
            metodo=MetodoPagamento.CARTAO_CREDITO, valor_centavos=1, cartao=_cartao("0119")
        )
    # Tolerância para a granularidade do relógio do laço de eventos (cerca de 15 ms no Windows).
    assert time.perf_counter() - inicio >= 0.04


async def test_cartao_ausente_e_erro_de_programacao() -> None:
    with pytest.raises(ValueError, match="cartão"):
        await GatewaySimulado().autorizar(
            metodo=MetodoPagamento.CARTAO_CREDITO, valor_centavos=1, cartao=None
        )


async def test_mesma_chave_devolve_a_mesma_autorizacao_sem_cobrar_de_novo() -> None:
    gateway = GatewaySimulado()
    argumentos = {
        "metodo": MetodoPagamento.CARTAO_CREDITO,
        "valor_centavos": 4590,
        "cartao": _cartao("0000"),
    }
    primeira = await gateway.autorizar(**argumentos, chave_idempotencia="POST|k-1")
    segunda = await gateway.autorizar(**argumentos, chave_idempotencia="POST|k-1")
    assert primeira == segunda == ResultadoAutorizacao(aprovado=True)
    assert gateway.autorizacoes_efetivas == 1
    await gateway.autorizar(**argumentos, chave_idempotencia="POST|k-2")
    await gateway.autorizar(**argumentos)
    assert gateway.autorizacoes_efetivas == 3


async def test_timeout_nao_fica_gravado_para_a_chave() -> None:
    gateway = GatewaySimulado()
    for _ in range(2):
        with pytest.raises(ErroDependenciaIndisponivel):
            await gateway.autorizar(
                metodo=MetodoPagamento.CARTAO_CREDITO,
                valor_centavos=1,
                cartao=_cartao("0119"),
                chave_idempotencia="k-to",
            )
