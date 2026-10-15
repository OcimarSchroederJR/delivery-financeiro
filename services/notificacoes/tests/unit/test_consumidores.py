import json
import uuid

import pytest

from notificacoes.adaptadores.mensageria.consumidores import tratar_evento, tratar_tarefa
from notificacoes.adaptadores.mensageria.topologia import FILA_WEBHOOKS
from notificacoes.aplicacao.tarefas import TIPO_TAREFA_WEBHOOK, Desfecho, Tarefa
from plataforma.correlation import obter_correlation_id
from plataforma.envelope import EnvelopeEvento


class ConfirmacaoFalsa:
    def __init__(self, registro: list[str]) -> None:
        self.registro = registro

    async def ack(self) -> None:
        self.registro.append("ack")

    async def nack(self, *, requeue: bool = True) -> None:
        self.registro.append(f"nack(requeue={requeue})")

    async def reject(self, *, requeue: bool = False) -> None:
        self.registro.append(f"reject(requeue={requeue})")


class EncaminhadorFalso:
    def __init__(self, registro: list[str], *, falhar: bool = False) -> None:
        self.registro = registro
        self.falhar = falhar

    async def reagendar(self, fila: str, numero: int, corpo: bytes, cabecalhos: object) -> None:
        if self.falhar:
            raise ConnectionError("broker fora")
        self.registro.append(f"reagendar({fila},{numero})")

    async def enviar_para_dlq(
        self, fila: str, corpo: bytes, cabecalhos: object, motivo: str
    ) -> None:
        self.registro.append(f"dlq({fila},{motivo})")


EVENTO = EnvelopeEvento.novo("pagamento.aprovado", {"cliente_id": "c1"}, correlation_id="cid-9")
CORPO_EVENTO = json.dumps(EVENTO.para_json()).encode()
CORPO_TAREFA = json.dumps(
    Tarefa(TIPO_TAREFA_WEBHOOK, uuid.uuid4(), EVENTO).para_envelope().para_json()
).encode()


async def test_evento_processado_e_confirmado_depois() -> None:
    registro: list[str] = []

    async def processar(envelope: EnvelopeEvento) -> None:
        registro.append(f"processado:{envelope.tipo}:{obter_correlation_id()}")

    await tratar_evento(CORPO_EVENTO, {}, ConfirmacaoFalsa(registro), processar, pausa_em_erro=0)
    assert registro == ["processado:pagamento.aprovado:cid-9", "ack"]


@pytest.mark.parametrize("corpo", [b"nao-json", b'{"tipo": "x"}'])
async def test_evento_invalido_vai_para_dlq(corpo: bytes) -> None:
    registro: list[str] = []

    async def processar(envelope: EnvelopeEvento) -> None:
        registro.append("nao devia processar")

    await tratar_evento(corpo, {}, ConfirmacaoFalsa(registro), processar, pausa_em_erro=0)
    assert registro == ["reject(requeue=False)"]


async def test_excecao_inesperada_faz_nack_com_requeue() -> None:
    registro: list[str] = []

    async def processar(envelope: EnvelopeEvento) -> None:
        raise RuntimeError("banco fora")

    await tratar_evento(CORPO_EVENTO, {}, ConfirmacaoFalsa(registro), processar, pausa_em_erro=0)
    assert registro == ["nack(requeue=True)"]


async def _tratar(desfecho: Desfecho, *, falhar_encaminhador: bool = False) -> list[str]:
    registro: list[str] = []

    async def processar(tarefa: Tarefa) -> Desfecho:
        registro.append(f"processada:{tarefa.tipo}")
        return desfecho

    await tratar_tarefa(
        CORPO_TAREFA,
        {"X-Correlation-ID": "cid-9"},
        ConfirmacaoFalsa(registro),
        processar,
        EncaminhadorFalso(registro, falhar=falhar_encaminhador),
        fila=FILA_WEBHOOKS,
        pausa_em_erro=0,
    )
    return registro


async def test_tarefa_concluida_ou_ignorada_so_confirma() -> None:
    assert await _tratar(Desfecho.concluida()) == ["processada:tarefa.webhook", "ack"]
    assert await _tratar(Desfecho.ignorada("x")) == ["processada:tarefa.webhook", "ack"]


async def test_tarefa_repetir_reagenda_e_depois_confirma() -> None:
    assert await _tratar(Desfecho.repetir(3, "HTTP 500")) == [
        "processada:tarefa.webhook",
        "reagendar(notificacoes.webhooks,3)",
        "ack",
    ]


async def test_tarefa_desistir_vai_para_dlq_e_depois_confirma() -> None:
    assert await _tratar(Desfecho.desistir("HTTP 503")) == [
        "processada:tarefa.webhook",
        "dlq(notificacoes.webhooks,HTTP 503)",
        "ack",
    ]


async def test_falha_ao_reagendar_faz_nack_sem_ack() -> None:
    assert await _tratar(Desfecho.repetir(1, "HTTP 500"), falhar_encaminhador=True) == [
        "processada:tarefa.webhook",
        "nack(requeue=True)",
    ]


async def test_tarefa_malformada_e_rejeitada() -> None:
    registro: list[str] = []

    async def processar(tarefa: Tarefa) -> Desfecho:
        return Desfecho.concluida()

    await tratar_tarefa(
        CORPO_EVENTO,  # um evento comum não é uma tarefa
        {},
        ConfirmacaoFalsa(registro),
        processar,
        EncaminhadorFalso(registro),
        fila=FILA_WEBHOOKS,
        pausa_em_erro=0,
    )
    assert registro == ["reject(requeue=False)"]
