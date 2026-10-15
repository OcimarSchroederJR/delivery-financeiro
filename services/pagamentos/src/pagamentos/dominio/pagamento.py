"""Entidade Pagamento, estornos e regra de antifraude (spec §4.1)."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

LIMITE_ANTIFRAUDE_CENTAVOS = 500_000
MOTIVO_ANTIFRAUDE = "analise_antifraude"
MOTIVO_SALDO_INSUFICIENTE = "saldo_insuficiente"


class MetodoPagamento(StrEnum):
    CARTAO_CREDITO = "cartao_credito"
    PIX = "pix"


class StatusPagamento(StrEnum):
    APROVADO = "aprovado"
    RECUSADO = "recusado"
    PARCIALMENTE_ESTORNADO = "parcialmente_estornado"
    ESTORNADO = "estornado"


STATUS_ESTORNAVEIS = frozenset({StatusPagamento.APROVADO, StatusPagamento.PARCIALMENTE_ESTORNADO})


def exige_analise_antifraude(valor_centavos: int) -> bool:
    """Regra 4: acima de R$ 5.000,00 (500000 centavos) o pagamento é recusado."""
    return valor_centavos > LIMITE_ANTIFRAUDE_CENTAVOS


@dataclass(frozen=True, slots=True)
class Estorno:
    id: UUID
    pagamento_id: UUID
    valor_centavos: int
    motivo: str
    criado_em: datetime


@dataclass(slots=True)
class Pagamento:
    id: UUID
    pedido_id: str
    cliente_id: str
    valor_centavos: int
    metodo: MetodoPagamento
    status: StatusPagamento
    motivo_recusa: str | None
    cartao_final: str | None
    criado_em: datetime
    atualizado_em: datetime
    estornos: list[Estorno] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.valor_centavos <= 0:
            raise ValueError("valor_centavos deve ser positivo")
        if self.cartao_final is not None and not (
            len(self.cartao_final) == 4
            and self.cartao_final.isascii()
            and self.cartao_final.isdigit()
        ):
            raise ValueError("cartao_final deve ter exatamente 4 dígitos")
        if (self.status == StatusPagamento.RECUSADO) != (self.motivo_recusa is not None):
            raise ValueError("motivo_recusa existe se, e somente se, o pagamento foi recusado")

    @classmethod
    def aprovado(
        cls,
        *,
        id: UUID,
        pedido_id: str,
        cliente_id: str,
        valor_centavos: int,
        metodo: MetodoPagamento,
        cartao_final: str | None,
        agora: datetime,
    ) -> Self:
        return cls(
            id=id,
            pedido_id=pedido_id,
            cliente_id=cliente_id,
            valor_centavos=valor_centavos,
            metodo=metodo,
            status=StatusPagamento.APROVADO,
            motivo_recusa=None,
            cartao_final=cartao_final,
            criado_em=agora,
            atualizado_em=agora,
        )

    @classmethod
    def recusado(
        cls,
        *,
        id: UUID,
        pedido_id: str,
        cliente_id: str,
        valor_centavos: int,
        metodo: MetodoPagamento,
        cartao_final: str | None,
        motivo: str,
        agora: datetime,
    ) -> Self:
        return cls(
            id=id,
            pedido_id=pedido_id,
            cliente_id=cliente_id,
            valor_centavos=valor_centavos,
            metodo=metodo,
            status=StatusPagamento.RECUSADO,
            motivo_recusa=motivo,
            cartao_final=cartao_final,
            criado_em=agora,
            atualizado_em=agora,
        )

    @property
    def efetivado(self) -> bool:
        """Aprovado em algum momento (inclui os estornados). Só um por pedido."""
        return self.status != StatusPagamento.RECUSADO

    @property
    def valor_estornado_centavos(self) -> int:
        return sum(estorno.valor_centavos for estorno in self.estornos)

    @property
    def saldo_estornavel_centavos(self) -> int:
        if self.status not in STATUS_ESTORNAVEIS:
            return 0
        return self.valor_centavos - self.valor_estornado_centavos
