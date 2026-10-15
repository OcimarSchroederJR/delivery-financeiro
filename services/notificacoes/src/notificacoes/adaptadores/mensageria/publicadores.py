"""Publicação nas filas internas: tarefas (relay do outbox) e retentativas/DLQ."""

from collections.abc import Mapping
from typing import Any

from faststream.rabbit import RabbitBroker

from notificacoes.adaptadores.mensageria.topologia import FILA_DLQ, FILAS_DE_TAREFA, nome_fila_retry
from plataforma.correlation import HEADER_CORRELATION_ID
from plataforma.envelope import EnvelopeEvento

TAMANHO_MAXIMO_MOTIVO = 500


def _cabecalhos_preservados(cabecalhos: Mapping[str, Any]) -> dict[str, Any]:
    """Só o correlation id segue adiante (descarta ``x-death`` e afins)."""
    correlation_id = cabecalhos.get(HEADER_CORRELATION_ID)
    return {} if correlation_id is None else {HEADER_CORRELATION_ID: str(correlation_id)}


class PublicadorDeTarefas:
    """Implementa ``plataforma.outbox.Publicador`` para o outbox de tarefas."""

    def __init__(self, broker: RabbitBroker) -> None:
        self._broker = broker

    async def publicar(self, envelope: EnvelopeEvento) -> None:
        fila = FILAS_DE_TAREFA.get(envelope.tipo)
        if fila is None:
            raise ValueError(f"Tipo de tarefa sem fila: {envelope.tipo}.")
        await self._broker.publish(
            envelope.para_json(),
            queue=fila,
            message_id=str(envelope.mensagem_id),
            correlation_id=envelope.correlation_id,
            headers={HEADER_CORRELATION_ID: envelope.correlation_id},
            persist=True,
        )


class EncaminhadorDeFalhas:
    """Republica o corpo original numa fila de retry (TTL) ou na DLQ."""

    def __init__(self, broker: RabbitBroker) -> None:
        self._broker = broker

    async def reagendar(
        self, fila: str, numero: int, corpo: bytes, cabecalhos: Mapping[str, Any]
    ) -> None:
        await self._broker.publish(
            corpo,
            queue=nome_fila_retry(fila, numero),
            headers={**_cabecalhos_preservados(cabecalhos), "x-retentativa": numero},
            persist=True,
        )

    async def enviar_para_dlq(
        self, fila: str, corpo: bytes, cabecalhos: Mapping[str, Any], motivo: str
    ) -> None:
        await self._broker.publish(
            corpo,
            queue=FILA_DLQ,
            headers={
                **_cabecalhos_preservados(cabecalhos),
                "x-fila-origem": fila,
                "x-motivo": motivo[:TAMANHO_MAXIMO_MOTIVO],
            },
            persist=True,
        )
