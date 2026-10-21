import uuid
from typing import Any

import pytest

from notificacoes.adaptadores.mensageria.publicadores import (
    EncaminhadorDeFalhas,
    PublicadorDeTarefas,
)
from notificacoes.adaptadores.mensageria.topologia import FILA_DLQ, FILA_EMAILS, FILA_WEBHOOKS
from notificacoes.aplicacao.tarefas import TIPO_TAREFA_EMAIL, Tarefa
from plataforma.envelope import EnvelopeEvento


class BrokerFalso:
    def __init__(self) -> None:
        self.publicadas: list[tuple[Any, dict[str, Any]]] = []

    async def publish(self, mensagem: Any, **opcoes: Any) -> None:
        self.publicadas.append((mensagem, opcoes))


async def test_publicador_de_tarefas_usa_a_fila_do_tipo() -> None:
    broker = BrokerFalso()
    evento = EnvelopeEvento.novo("pagamento.aprovado", {}, correlation_id="cid-7")
    envelope = Tarefa(TIPO_TAREFA_EMAIL, uuid.uuid4(), evento).para_envelope()
    await PublicadorDeTarefas(broker).publicar(envelope)  # type: ignore[arg-type]
    [(mensagem, opcoes)] = broker.publicadas
    assert mensagem == envelope.para_json()
    assert (opcoes["queue"], opcoes["persist"], opcoes["message_id"]) == (
        FILA_EMAILS,
        True,
        str(envelope.mensagem_id),
    )
    assert opcoes["headers"] == {"X-Correlation-ID": "cid-7"}


async def test_publicador_de_tarefas_recusa_tipo_sem_fila() -> None:
    with pytest.raises(ValueError, match="sem fila"):
        await PublicadorDeTarefas(BrokerFalso()).publicar(  # type: ignore[arg-type]
            EnvelopeEvento.novo("pagamento.aprovado", {})
        )


async def test_encaminhador_reagenda_e_manda_para_dlq_preservando_correlation_id() -> None:
    broker = BrokerFalso()
    encaminhador = EncaminhadorDeFalhas(broker)  # type: ignore[arg-type]
    cabecalhos = {"X-Correlation-ID": "cid-1", "x-death": [{"count": 1}]}
    await encaminhador.reagendar(FILA_WEBHOOKS, 2, b"{}", cabecalhos)
    await encaminhador.enviar_para_dlq(FILA_WEBHOOKS, b"{}", cabecalhos, "HTTP 503")
    (corpo_retry, retry), (corpo_dlq, dlq) = broker.publicadas
    assert (corpo_retry, retry["queue"], retry["persist"]) == (
        b"{}",
        "notificacoes.webhooks.retry.2",
        True,
    )
    assert retry["headers"] == {"X-Correlation-ID": "cid-1", "x-retentativa": 2}
    assert (corpo_dlq, dlq["queue"]) == (b"{}", FILA_DLQ)
    assert dlq["headers"] == {
        "X-Correlation-ID": "cid-1",
        "x-fila-origem": FILA_WEBHOOKS,
        "x-motivo": "HTTP 503",
    }
