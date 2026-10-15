"""Tarefas internas de entrega (e-mail e webhook) e o desfecho de cada tentativa.

Uma tarefa viaja como um ``EnvelopeEvento`` de tipo ``tarefa.email`` ou
``tarefa.webhook`` (outbox de tarefas → fila), com o evento original dentro.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from plataforma.envelope import EnvelopeEvento

TIPO_TAREFA_EMAIL = "tarefa.email"
TIPO_TAREFA_WEBHOOK = "tarefa.webhook"
TIPOS_DE_TAREFA = frozenset({TIPO_TAREFA_EMAIL, TIPO_TAREFA_WEBHOOK})


@dataclass(frozen=True, slots=True)
class Tarefa:
    tipo: str
    notificacao_id: uuid.UUID
    evento: EnvelopeEvento

    def para_envelope(self) -> EnvelopeEvento:
        return EnvelopeEvento.novo(
            self.tipo,
            {"notificacao_id": str(self.notificacao_id), "evento": self.evento.para_json()},
            correlation_id=self.evento.correlation_id,
        )

    @classmethod
    def de_envelope(cls, envelope: EnvelopeEvento) -> Self:
        if envelope.tipo not in TIPOS_DE_TAREFA:
            raise ValueError(f"Tarefa de tipo desconhecido: {envelope.tipo}.")
        try:
            notificacao_id = uuid.UUID(str(envelope.dados["notificacao_id"]))
            evento = EnvelopeEvento.model_validate(envelope.dados["evento"])
        except (KeyError, ValueError) as erro:  # ValidationError é ValueError
            raise ValueError("Tarefa malformada.") from erro
        return cls(tipo=envelope.tipo, notificacao_id=notificacao_id, evento=evento)


class TipoDesfecho(StrEnum):
    CONCLUIDA = "concluida"
    REPETIR = "repetir"
    DESISTIR = "desistir"
    IGNORADA = "ignorada"


@dataclass(frozen=True, slots=True)
class Desfecho:
    """O que o consumidor deve fazer com a mensagem depois do commit."""

    tipo: TipoDesfecho
    retentativa: int | None = None
    motivo: str | None = None

    @classmethod
    def concluida(cls) -> Self:
        return cls(TipoDesfecho.CONCLUIDA)

    @classmethod
    def ignorada(cls, motivo: str) -> Self:
        return cls(TipoDesfecho.IGNORADA, motivo=motivo)

    @classmethod
    def repetir(cls, retentativa: int, motivo: str) -> Self:
        return cls(TipoDesfecho.REPETIR, retentativa=retentativa, motivo=motivo)

    @classmethod
    def desistir(cls, motivo: str) -> Self:
        return cls(TipoDesfecho.DESISTIR, motivo=motivo)
