"""Caso de uso: criar (autorizar) o pagamento de um pedido (spec §4.1)."""

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pagamentos.aplicacao.idempotencia import ReservaIdempotencia
from pagamentos.aplicacao.portas import (
    Apresentador,
    ConsultaPedidos,
    FabricaUnidadeDeTrabalho,
    GatewayDePagamento,
    GeradorDeId,
    Relogio,
    ResultadoAutorizacao,
)
from pagamentos.aplicacao.solicitante import Solicitante
from pagamentos.dominio.cartao import DadosCartao
from pagamentos.dominio.erros import (
    PagamentoRecusado,
    PedidoCancelado,
    PedidoDeOutroCliente,
    PedidoInexistente,
    PedidoJaPago,
    PedidoSemValor,
)
from pagamentos.dominio.eventos import evento_de_registro
from pagamentos.dominio.pagamento import (
    MOTIVO_ANTIFRAUDE,
    MetodoPagamento,
    Pagamento,
    exige_analise_antifraude,
)
from pagamentos.dominio.pedido import Pedido
from plataforma.logs import obter_logger
from plataforma.tempo import agora_utc

_log = obter_logger(__name__)

MOTIVO_RECUSA_PADRAO = "recusado_pelo_emissor"


@dataclass(frozen=True, slots=True)
class ComandoCriarPagamento:
    pedido_id: str
    metodo: MetodoPagamento
    cartao: DadosCartao | None = None

    def __post_init__(self) -> None:
        if self.metodo == MetodoPagamento.CARTAO_CREDITO and self.cartao is None:
            raise ValueError("pagamento com cartão exige os dados do cartão")

    @property
    def cartao_final(self) -> str | None:
        if self.metodo == MetodoPagamento.CARTAO_CREDITO and self.cartao is not None:
            return self.cartao.ultimos_digitos
        return None


class CriarPagamento:
    def __init__(
        self,
        *,
        fabrica_uow: FabricaUnidadeDeTrabalho,
        pedidos: ConsultaPedidos,
        gateway: GatewayDePagamento,
        apresentador: Apresentador,
        relogio: Relogio = agora_utc,
        gerar_id: GeradorDeId = uuid4,
    ) -> None:
        self._fabrica_uow = fabrica_uow
        self._pedidos = pedidos
        self._gateway = gateway
        self._apresentador = apresentador
        self._relogio = relogio
        self._gerar_id = gerar_id

    async def executar(
        self,
        comando: ComandoCriarPagamento,
        solicitante: Solicitante,
        reserva: ReservaIdempotencia | None = None,
    ) -> Pagamento:
        pedido = await self._validar_pedido(comando.pedido_id, solicitante)
        async with self._fabrica_uow() as uow:
            if await uow.pagamentos.existe_efetivado(comando.pedido_id):
                raise PedidoJaPago()
        resultado = await self._autorizar(comando, pedido.valor_total_centavos)
        pagamento = self._registrar(comando, pedido, resultado)
        async with self._fabrica_uow() as uow:
            await uow.pagamentos.adicionar(pagamento)
            tipo, dados = evento_de_registro(pagamento)
            uow.eventos.registrar(tipo, dados)
            if reserva is not None:
                status, corpo = self._resposta(pagamento)
                await uow.chaves_idempotencia.concluir(
                    reserva.escopo, reserva.chave, status_resposta=status, corpo_resposta=corpo
                )
            await uow.commit()
        if not pagamento.efetivado:
            _log.info(
                "pagamento_recusado",
                pagamento_id=str(pagamento.id),
                pedido_id=pagamento.pedido_id,
                motivo=pagamento.motivo_recusa,
            )
            raise self._recusa(pagamento)
        _log.info(
            "pagamento_aprovado",
            pagamento_id=str(pagamento.id),
            pedido_id=pagamento.pedido_id,
            valor_centavos=pagamento.valor_centavos,
            metodo=pagamento.metodo.value,
        )
        return pagamento

    async def _validar_pedido(self, pedido_id: str, solicitante: Solicitante) -> Pedido:
        pedido = await self._pedidos.obter(pedido_id, token=solicitante.token)
        if pedido is None:
            raise PedidoInexistente()
        if solicitante.e_cliente and pedido.cliente_id != solicitante.id:
            raise PedidoDeOutroCliente()
        if pedido.cancelado:
            raise PedidoCancelado()
        if pedido.valor_total_centavos <= 0:
            raise PedidoSemValor()
        return pedido

    async def _autorizar(
        self, comando: ComandoCriarPagamento, valor_centavos: int
    ) -> ResultadoAutorizacao:
        if exige_analise_antifraude(valor_centavos):
            return ResultadoAutorizacao(aprovado=False, motivo_recusa=MOTIVO_ANTIFRAUDE)
        cartao = comando.cartao if comando.metodo == MetodoPagamento.CARTAO_CREDITO else None
        return await self._gateway.autorizar(
            metodo=comando.metodo, valor_centavos=valor_centavos, cartao=cartao
        )

    def _registrar(
        self, comando: ComandoCriarPagamento, pedido: Pedido, resultado: ResultadoAutorizacao
    ) -> Pagamento:
        if resultado.aprovado:
            return Pagamento.aprovado(
                id=self._gerar_id(),
                pedido_id=comando.pedido_id,
                cliente_id=pedido.cliente_id,
                valor_centavos=pedido.valor_total_centavos,
                metodo=comando.metodo,
                cartao_final=comando.cartao_final,
                agora=self._relogio(),
            )
        return Pagamento.recusado(
            id=self._gerar_id(),
            pedido_id=comando.pedido_id,
            cliente_id=pedido.cliente_id,
            valor_centavos=pedido.valor_total_centavos,
            metodo=comando.metodo,
            cartao_final=comando.cartao_final,
            motivo=resultado.motivo_recusa or MOTIVO_RECUSA_PADRAO,
            agora=self._relogio(),
        )

    def _resposta(self, pagamento: Pagamento) -> tuple[int, dict[str, Any]]:
        if pagamento.efetivado:
            return 201, self._apresentador.pagamento(pagamento)
        recusa = self._recusa(pagamento)
        return recusa.status_http, self._apresentador.erro(recusa)

    @staticmethod
    def _recusa(pagamento: Pagamento) -> PagamentoRecusado:
        return PagamentoRecusado(pagamento.id, pagamento.motivo_recusa or MOTIVO_RECUSA_PADRAO)
