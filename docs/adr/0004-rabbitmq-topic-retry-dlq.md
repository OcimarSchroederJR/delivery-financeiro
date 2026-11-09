# ADR 0004: RabbitMQ com exchange topic, retry por TTL e DLQ

- **Status:** aceita

## Contexto

Os eventos têm vários interessados (hoje Notificações, amanhã qualquer equipe) e as falhas de entrega são comuns: SMTP fora, webhook do cliente lento, banco indisponível. Uma mensagem com problema não pode ficar voltando para a fila para sempre nem bloquear as demais.

## Decisão

- Um exchange `financeiro.eventos` do tipo **topic**, durável. A routing key é o `tipo` do evento (`pagamento.aprovado`, `disputa.resolvida`). Cada consumidor liga a fila só nas chaves que lhe interessam (`#` em `notificacoes.eventos`).
- Publicação com `persist`, `mandatory` e publisher confirms: mensagem sem fila ligada gera erro em vez de sumir, e o evento continua pendente no outbox.
- **Retry por TTL e dead-letter:** para cada fila principal existem as filas `<fila>.retry.1` a `.5`, com `x-message-ttl` de 1 s, 5 s, 30 s, 2 min e 10 min. Ao expirar, a mensagem volta para a fila principal pelo exchange padrão. O consumidor republica na fila de retry correspondente e confirma (ack) a original.
- **DLQ:** `notificacoes.dlq` recebe o que esgotou as tentativas, as mensagens malformadas e as falhas definitivas. O contador de falhas inesperadas viaja no header `x-falhas-inesperadas`.
- Ack manual: cada handler termina em exatamente uma ação (ack, reject sem requeue, ou nack só se nem a republicação funcionou). Não há requeue infinito.

## Alternativas consideradas

- **Retry em memória no consumidor (sleep e nova tentativa):** perde a tentativa se o processo morrer e deixa o consumidor ocupado.
- **Plugin de mensagens atrasadas:** menos filas, mas é um plugin a mais para instalar e manter.
- **Exchange direct ou fanout:** direct não aceita padrões; fanout entregaria tudo a todos.
- **Requeue com limite de entregas do broker:** não dá backoff entre as tentativas.

## Consequências

- Backoff crescente sem código de agendamento: o relógio é do broker.
- São mais filas para declarar. O RabbitMQ recusa redeclarar fila com argumentos diferentes; para mudar os TTLs é preciso apagar as filas de retry antes.
- A DLQ não é reprocessada automaticamente: alguém precisa olhar.
- Retry e DLQ existem hoje só em Notificações, único serviço que consome do broker. Pagamentos e Avaliações só publicam.

**Onde está no código:** `libs/plataforma/src/plataforma/mensageria.py` (exchange e publicador), `services/notificacoes/src/notificacoes/adaptadores/mensageria/topologia.py` (filas, retry, DLQ), `services/notificacoes/src/notificacoes/adaptadores/mensageria/consumidores.py` (ack manual e limite de falhas), `services/notificacoes/src/notificacoes/adaptadores/mensageria/publicadores.py` (`reagendar`, `enviar_para_dlq`), `services/notificacoes/src/notificacoes/config.py` (`TTLS_RETRY_PADRAO_MS`).
