"""Documentação AsyncAPI dos eventos do serviço (spec §3.5).

A publicação real é feita pelo relay do outbox; aqui só declaramos os canais
para gerar ``docs/asyncapi/avaliacoes.json``. Os modelos ``Dados*`` descrevem
exatamente o que ``avaliacoes.aplicacao.eventos`` monta (há teste garantindo).
"""

import uuid
from typing import Literal

from faststream.rabbit import RabbitBroker
from pydantic import BaseModel, Field

from avaliacoes.aplicacao.eventos import (
    AVALIACAO_REGISTRADA,
    DISPUTA_ABERTA,
    DISPUTA_ESTORNO_FALHOU,
    DISPUTA_RESOLVIDA,
)
from avaliacoes.dominio.disputa import Decisao, MotivoDisputa
from plataforma.mensageria import EXCHANGE_EVENTOS, criar_broker_especificacao
from plataforma.tempo import DataHoraUTC


class DadosAvaliacaoRegistrada(BaseModel):
    avaliacao_id: uuid.UUID
    pedido_id: str
    restaurante_id: str
    cliente_id: str
    nota_restaurante: int
    nota_entrega: int | None


class DadosDisputaAberta(BaseModel):
    disputa_id: uuid.UUID
    pedido_id: str
    cliente_id: str
    motivo: MotivoDisputa
    valor_solicitado_centavos: int


class DadosDisputaResolvida(BaseModel):
    disputa_id: uuid.UUID
    pedido_id: str
    cliente_id: str
    decisao: Decisao
    valor_estornado_centavos: int


class DadosDisputaEstornoFalhou(BaseModel):
    disputa_id: uuid.UUID
    pedido_id: str
    motivo: str = Field(
        description=(
            "Código da recusa definitiva de Pagamentos (ex.: PAGAMENTO_NAO_ESTORNAVEL, "
            "VALOR_EXCEDE_SALDO_ESTORNAVEL, HTTP_404) ou RESULTADO_INCERTO quando as "
            "tentativas se esgotaram com falha transitória: o estorno pode ter sido feito; "
            "confira em Pagamentos antes de agir."
        )
    )


class _Envelope(BaseModel):
    mensagem_id: uuid.UUID
    versao: Literal[1] = 1
    ocorrido_em: DataHoraUTC
    correlation_id: str


class EventoAvaliacaoRegistrada(_Envelope):
    tipo: Literal["avaliacao.registrada"]
    dados: DadosAvaliacaoRegistrada


class EventoDisputaAberta(_Envelope):
    tipo: Literal["disputa.aberta"]
    dados: DadosDisputaAberta


class EventoDisputaResolvida(_Envelope):
    tipo: Literal["disputa.resolvida"]
    dados: DadosDisputaResolvida


class EventoDisputaEstornoFalhou(_Envelope):
    tipo: Literal["disputa.estorno_falhou"]
    dados: DadosDisputaEstornoFalhou


EVENTOS: dict[str, tuple[type[_Envelope], type[BaseModel], str]] = {
    AVALIACAO_REGISTRADA: (
        EventoAvaliacaoRegistrada,
        DadosAvaliacaoRegistrada,
        "Avaliação registrada para um pedido entregue.",
    ),
    DISPUTA_ABERTA: (
        EventoDisputaAberta,
        DadosDisputaAberta,
        "Cliente abriu uma disputa sobre um pedido pago.",
    ),
    DISPUTA_RESOLVIDA: (
        EventoDisputaResolvida,
        DadosDisputaResolvida,
        "Disputa encerrada: procedente (estorno feito) ou improcedente (valor 0).",
    ),
    DISPUTA_ESTORNO_FALHOU: (
        EventoDisputaEstornoFalhou,
        DadosDisputaEstornoFalhou,
        "Estorno da disputa falhou de forma definitiva; o admin precisa agir.",
    ),
}


def criar_broker_documentado() -> RabbitBroker:
    broker = criar_broker_especificacao(
        "Eventos do serviço de Avaliações (exchange financeiro.eventos)."
    )
    for tipo, (evento, _dados, descricao) in EVENTOS.items():
        broker.publisher(
            routing_key=tipo,
            exchange=EXCHANGE_EVENTOS,
            title=tipo,
            schema=evento,
            description=descricao,
        )
    return broker
