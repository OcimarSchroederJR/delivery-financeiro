import uuid
from typing import Any

import pytest

from notificacoes.aplicacao.tarefas import (
    TIPO_TAREFA_EMAIL,
    Desfecho,
    Tarefa,
    TipoDesfecho,
)
from plataforma.envelope import EnvelopeEvento


def test_tarefa_ida_e_volta_pelo_envelope() -> None:
    evento = EnvelopeEvento.novo("pagamento.aprovado", {"cliente_id": "c1"}, correlation_id="cid-1")
    tarefa = Tarefa(TIPO_TAREFA_EMAIL, uuid.uuid4(), evento)
    envelope = tarefa.para_envelope()
    assert envelope.tipo == "tarefa.email"
    assert envelope.correlation_id == "cid-1"
    assert envelope.dados["notificacao_id"] == str(tarefa.notificacao_id)
    volta = Tarefa.de_envelope(EnvelopeEvento.model_validate(envelope.para_json()))
    assert (volta.tipo, volta.notificacao_id) == (tarefa.tipo, tarefa.notificacao_id)
    assert volta.evento.para_json() == evento.para_json()


def _tarefa_json(**dados: Any) -> EnvelopeEvento:
    return EnvelopeEvento.novo("tarefa.webhook", dados)


@pytest.mark.parametrize(
    "envelope",
    [
        EnvelopeEvento.novo("pagamento.aprovado", {}),
        _tarefa_json(evento={}),
        _tarefa_json(notificacao_id="nao-uuid", evento={}),
        _tarefa_json(notificacao_id=str(uuid.uuid4()), evento={"tipo": "x"}),
    ],
)
def test_tarefa_malformada(envelope: EnvelopeEvento) -> None:
    with pytest.raises(ValueError, match="arefa"):
        Tarefa.de_envelope(envelope)


def test_desfechos() -> None:
    assert Desfecho.concluida() == Desfecho(TipoDesfecho.CONCLUIDA)
    repetir = Desfecho.repetir(2, "HTTP 500")
    assert (repetir.tipo, repetir.retentativa, repetir.motivo) == (
        TipoDesfecho.REPETIR,
        2,
        "HTTP 500",
    )
    assert Desfecho.desistir("x").tipo is TipoDesfecho.DESISTIR
    assert Desfecho.ignorada("y").tipo is TipoDesfecho.IGNORADA
