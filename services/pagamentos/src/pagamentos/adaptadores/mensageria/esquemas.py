"""Esquemas (AsyncAPI) dos eventos publicados por Pagamentos.

Os campos de ``dados`` são exatamente os da spec §3.5. Consumidores devem ignorar
campos desconhecidos; mudança incompatível exige incrementar ``versao``.
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from pagamentos.dominio.eventos import (
    TIPO_PAGAMENTO_APROVADO,
    TIPO_PAGAMENTO_ESTORNADO,
    TIPO_PAGAMENTO_RECUSADO,
)
from pagamentos.dominio.pagamento import MetodoPagamento
from plataforma.tempo import DataHoraUTC


class DadosPagamentoAprovado(BaseModel):
    pagamento_id: UUID
    pedido_id: str
    cliente_id: str
    valor_centavos: int
    metodo: MetodoPagamento


class DadosPagamentoRecusado(BaseModel):
    pagamento_id: UUID
    pedido_id: str
    cliente_id: str
    valor_centavos: int
    motivo: str = Field(examples=["analise_antifraude", "saldo_insuficiente"])


class DadosPagamentoEstornado(BaseModel):
    pagamento_id: UUID
    estorno_id: UUID
    pedido_id: str
    cliente_id: str
    valor_centavos: int = Field(description="Valor deste estorno (não o total do pagamento).")
    motivo: str


class _Envelope(BaseModel):
    mensagem_id: UUID
    versao: Literal[1] = 1
    ocorrido_em: DataHoraUTC
    correlation_id: str


class EventoPagamentoAprovado(_Envelope):
    tipo: Literal["pagamento.aprovado"]
    dados: DadosPagamentoAprovado


class EventoPagamentoRecusado(_Envelope):
    tipo: Literal["pagamento.recusado"]
    dados: DadosPagamentoRecusado


class EventoPagamentoEstornado(_Envelope):
    tipo: Literal["pagamento.estornado"]
    dados: DadosPagamentoEstornado


@dataclass(frozen=True, slots=True)
class EventoDocumentado:
    envelope: type[BaseModel]
    dados: type[BaseModel]
    descricao: str


EVENTOS_PUBLICADOS: dict[str, EventoDocumentado] = {
    TIPO_PAGAMENTO_APROVADO: EventoDocumentado(
        EventoPagamentoAprovado, DadosPagamentoAprovado, "Pagamento aprovado (cartão ou Pix)."
    ),
    TIPO_PAGAMENTO_RECUSADO: EventoDocumentado(
        EventoPagamentoRecusado,
        DadosPagamentoRecusado,
        "Pagamento recusado pelo antifraude ou pelo gateway; a tentativa fica registrada.",
    ),
    TIPO_PAGAMENTO_ESTORNADO: EventoDocumentado(
        EventoPagamentoEstornado,
        DadosPagamentoEstornado,
        "Estorno total ou parcial registrado (um evento por estorno).",
    ),
}
