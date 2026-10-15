import json

import aio_pika
import pytest

from plataforma.envelope import EnvelopeEvento
from plataforma.mensageria import NOME_EXCHANGE_EVENTOS, PublicadorRabbit, criar_broker

pytestmark = pytest.mark.integracao


async def test_publica_no_exchange_topic_com_routing_key_e_headers(rabbitmq_url: str) -> None:
    publicador = PublicadorRabbit(criar_broker(rabbitmq_url))
    await publicador.iniciar()
    conexao = await aio_pika.connect(rabbitmq_url)
    try:
        canal = await conexao.channel()
        exchange = await canal.get_exchange(NOME_EXCHANGE_EVENTOS)
        fila = await canal.declare_queue(exclusive=True)
        await fila.bind(exchange, routing_key="pagamento.*")

        envelope = EnvelopeEvento.novo("pagamento.aprovado", {"pagamento_id": "p1"})
        await publicador.publicar(envelope)

        mensagem = await fila.get(timeout=5)
        await mensagem.ack()
        assert json.loads(mensagem.body) == envelope.para_json()
        assert mensagem.message_id == str(envelope.mensagem_id)
        assert mensagem.correlation_id == envelope.correlation_id
        assert mensagem.headers["X-Correlation-ID"] == envelope.correlation_id
        assert mensagem.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
    finally:
        await conexao.close()
        await publicador.encerrar()
