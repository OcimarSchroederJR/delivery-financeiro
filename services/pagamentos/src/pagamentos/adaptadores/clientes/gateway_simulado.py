"""Gateway de pagamento simulado (spec §4.1, regra 5).

Decide pelos 4 últimos dígitos do cartão: ``0002`` recusa por saldo insuficiente,
``0119`` simula timeout (vira 503 sem persistir nada), qualquer outro final aprova.
Pix é sempre aprovado. Nunca recebe nem loga mais que os 4 últimos dígitos.
"""

import asyncio

from pagamentos.aplicacao.portas import ResultadoAutorizacao
from pagamentos.dominio.cartao import DadosCartao
from pagamentos.dominio.pagamento import MOTIVO_SALDO_INSUFICIENTE, MetodoPagamento
from plataforma.erros import ErroDependenciaIndisponivel
from plataforma.logs import obter_logger

_log = obter_logger(__name__)

DEPENDENCIA_GATEWAY = "gateway"
FINAL_RECUSA_SALDO = "0002"
FINAL_TIMEOUT = "0119"


class GatewaySimulado:
    def __init__(self, *, atraso_timeout: float = 0.0) -> None:
        self._atraso_timeout = atraso_timeout

    async def autorizar(
        self, *, metodo: MetodoPagamento, valor_centavos: int, cartao: DadosCartao | None
    ) -> ResultadoAutorizacao:
        if metodo == MetodoPagamento.PIX:
            return ResultadoAutorizacao(aprovado=True)
        if cartao is None:
            raise ValueError("pagamento com cartão exige os dados do cartão")
        final = cartao.ultimos_digitos
        if final == FINAL_TIMEOUT:
            await asyncio.sleep(self._atraso_timeout)
            _log.warning("gateway_sem_resposta", cartao_final=final, valor_centavos=valor_centavos)
            raise ErroDependenciaIndisponivel(
                DEPENDENCIA_GATEWAY, "O gateway de pagamento não respondeu a tempo."
            )
        if final == FINAL_RECUSA_SALDO:
            return ResultadoAutorizacao(aprovado=False, motivo_recusa=MOTIVO_SALDO_INSUFICIENTE)
        return ResultadoAutorizacao(aprovado=True)
