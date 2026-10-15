"""Visão do pedido da Eq. 3 que interessa a Pagamentos."""

from dataclasses import dataclass

STATUS_CANCELADO = "cancelado"


@dataclass(frozen=True, slots=True)
class Pedido:
    id: str
    cliente_id: str
    valor_total_centavos: int
    status: str

    @property
    def cancelado(self) -> bool:
        return self.status == STATUS_CANCELADO
