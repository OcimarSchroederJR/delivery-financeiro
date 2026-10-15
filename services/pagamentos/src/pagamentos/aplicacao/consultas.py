"""Consultas de pagamentos e estornos, com visibilidade por papel."""

from uuid import UUID

from pagamentos.aplicacao.portas import FabricaUnidadeDeTrabalho
from pagamentos.aplicacao.solicitante import Solicitante
from pagamentos.dominio.erros import PagamentoNaoEncontrado
from pagamentos.dominio.pagamento import Estorno, Pagamento


class ConsultasPagamentos:
    def __init__(self, fabrica_uow: FabricaUnidadeDeTrabalho) -> None:
        self._fabrica_uow = fabrica_uow

    async def obter(self, pagamento_id: UUID, solicitante: Solicitante) -> Pagamento:
        """Cliente só vê os seus; para os demais a resposta é 404 (não vaza existência)."""
        async with self._fabrica_uow() as uow:
            pagamento = await uow.pagamentos.obter(pagamento_id)
        if pagamento is None or (solicitante.e_cliente and pagamento.cliente_id != solicitante.id):
            raise PagamentoNaoEncontrado()
        return pagamento

    async def listar(
        self, solicitante: Solicitante, *, pedido_id: str | None, deslocamento: int, limite: int
    ) -> tuple[list[Pagamento], int]:
        cliente_id = solicitante.id if solicitante.e_cliente else None
        async with self._fabrica_uow() as uow:
            return await uow.pagamentos.listar(
                pedido_id=pedido_id,
                cliente_id=cliente_id,
                deslocamento=deslocamento,
                limite=limite,
            )

    async def listar_estornos(self, pagamento_id: UUID, solicitante: Solicitante) -> list[Estorno]:
        return list((await self.obter(pagamento_id, solicitante)).estornos)
