import json
import uuid
from collections.abc import Mapping
from typing import Any

import pytest
from faststream.rabbit import RabbitBroker

from notificacoes.adaptadores.mensageria.consumidores import (
    Processadores,
    registrar_consumidores,
    tratar_evento,
    tratar_tarefa,
)
from notificacoes.adaptadores.mensageria.topologia import (
    FILA_EVENTOS,
    FILA_WEBHOOKS,
    HEADER_FALHAS_INESPERADAS,
)
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
        self.cabecalhos: dict[str, Any] = {}

    async def reagendar(
        self, fila: str, numero: int, corpo: bytes, cabecalhos: Mapping[str, Any]
    ) -> None:
        if self.falhar:
            raise ConnectionError("broker fora")
        self.cabecalhos = dict(cabecalhos)
        self.registro.append(f"reagendar({fila},{numero})")

    async def enviar_para_dlq(
        self, fila: str, corpo: bytes, cabecalhos: Mapping[str, Any], motivo: str
    ) -> None:
        if self.falhar:
            raise ConnectionError("broker fora")
        self.registro.append(f"dlq({fila},{motivo})")


EVENTO = EnvelopeEvento.novo("pagamento.aprovado", {"cliente_id": "c1"}, correlation_id="cid-9")
CORPO_EVENTO = json.dumps(EVENTO.para_json()).encode()
CORPO_TAREFA = json.dumps(
    Tarefa(TIPO_TAREFA_WEBHOOK, uuid.uuid4(), EVENTO).para_envelope().para_json()
).encode()


async def _evento(
    corpo: bytes,
    cabecalhos: Mapping[str, Any],
    registro: list[str],
    processar: Any,
    encaminhador: "EncaminhadorFalso | None" = None,
) -> None:
    await tratar_evento(
        corpo,
        cabecalhos,
        ConfirmacaoFalsa(registro),
        processar,
        encaminhador or EncaminhadorFalso(registro),
        max_falhas=5,
        pausa_em_erro=0,
    )


async def test_evento_processado_e_confirmado_depois() -> None:
    registro: list[str] = []

    async def processar(envelope: EnvelopeEvento) -> None:
        registro.append(f"processado:{envelope.tipo}:{obter_correlation_id()}")

    await _evento(CORPO_EVENTO, {}, registro, processar)
    assert registro == ["processado:pagamento.aprovado:cid-9", "ack"]


@pytest.mark.parametrize("corpo", [b"nao-json", b'{"tipo": "x"}'])
async def test_evento_invalido_vai_para_dlq(corpo: bytes) -> None:
    registro: list[str] = []

    async def processar(envelope: EnvelopeEvento) -> None:
        registro.append("nao devia processar")

    await _evento(corpo, {}, registro, processar)
    assert registro == ["reject(requeue=False)"]


async def _quebra(_entrada: object) -> Desfecho:
    raise RuntimeError("banco fora")


async def test_excecao_inesperada_reagenda_com_contador_em_vez_de_requeue() -> None:
    registro: list[str] = []
    encaminhador = EncaminhadorFalso(registro)
    await _evento(CORPO_EVENTO, {"X-Correlation-ID": "cid-9"}, registro, _quebra, encaminhador)
    assert registro == [f"reagendar({FILA_EVENTOS},1)", "ack"]
    assert encaminhador.cabecalhos[HEADER_FALHAS_INESPERADAS] == 1


async def test_excecao_inesperada_soma_ao_contador_recebido() -> None:
    registro: list[str] = []
    encaminhador = EncaminhadorFalso(registro)
    await _evento(CORPO_EVENTO, {HEADER_FALHAS_INESPERADAS: 3}, registro, _quebra, encaminhador)
    assert registro == [f"reagendar({FILA_EVENTOS},4)", "ack"]
    assert encaminhador.cabecalhos[HEADER_FALHAS_INESPERADAS] == 4


async def test_excecao_inesperada_depois_do_limite_vai_para_dlq() -> None:
    registro: list[str] = []
    await _evento(CORPO_EVENTO, {HEADER_FALHAS_INESPERADAS: 5}, registro, _quebra)
    assert registro == [
        f"dlq({FILA_EVENTOS},Falha inesperada repetida 6 vezes: RuntimeError)",
        "ack",
    ]


async def test_broker_fora_ao_reagendar_apos_excecao_faz_nack() -> None:
    registro: list[str] = []
    await _evento(CORPO_EVENTO, {}, registro, _quebra, EncaminhadorFalso(registro, falhar=True))
    assert registro == ["nack(requeue=True)"]


async def test_tarefa_com_excecao_inesperada_reagenda_e_depois_vai_para_dlq() -> None:
    for recebidas, esperado in (
        (0, f"reagendar({FILA_WEBHOOKS},1)"),
        (5, f"dlq({FILA_WEBHOOKS},Falha inesperada repetida 6 vezes: RuntimeError)"),
    ):
        registro: list[str] = []
        await tratar_tarefa(
            CORPO_TAREFA,
            {HEADER_FALHAS_INESPERADAS: recebidas},
            ConfirmacaoFalsa(registro),
            _quebra,
            EncaminhadorFalso(registro),
            fila=FILA_WEBHOOKS,
            max_falhas=5,
            pausa_em_erro=0,
        )
        assert registro == [esperado, "ack"]


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
        max_falhas=5,
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
        max_falhas=5,
        pausa_em_erro=0,
    )
    assert registro == ["reject(requeue=False)"]


def test_consumidores_tem_prefetch_limitado_e_canal_proprio() -> None:
    broker = RabbitBroker()

    async def nada(_entrada: object) -> Desfecho:
        return Desfecho.concluida()

    registrar_consumidores(
        broker,
        Processadores(distribuir=nada, enviar_email=nada, entregar_webhook=nada),
        EncaminhadorFalso([]),
        max_falhas=5,
        prefetch=10,
    )
    prefetch = {
        assinante.queue.name: assinante.channel.prefetch_count
        for assinante in broker.subscribers
        if assinante.channel is not None
    }
    assert prefetch == {
        "notificacoes.eventos": 10,
        "notificacoes.emails": 10,
        "notificacoes.webhooks": 10,
    }
