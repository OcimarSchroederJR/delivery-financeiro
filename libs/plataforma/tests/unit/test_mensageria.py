from faststream.rabbit import ExchangeType

from plataforma.mensageria import EXCHANGE_EVENTOS, NOME_EXCHANGE_EVENTOS, criar_broker


def test_exchange_de_eventos_e_topic_duravel() -> None:
    assert EXCHANGE_EVENTOS.name == NOME_EXCHANGE_EVENTOS == "financeiro.eventos"
    assert EXCHANGE_EVENTOS.type == ExchangeType.TOPIC
    assert EXCHANGE_EVENTOS.durable is True


def test_criar_broker_com_e_sem_telemetria() -> None:
    assert criar_broker("amqp://guest:guest@localhost:5672/") is not None
    assert criar_broker("amqp://guest:guest@localhost:5672/", telemetria=True) is not None
