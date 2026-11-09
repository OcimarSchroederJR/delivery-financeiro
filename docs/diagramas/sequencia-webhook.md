# Sequência: entrega de webhook

Notificações consome cada evento de `financeiro.eventos`, cria uma tarefa por assinatura ativa e entrega o POST assinado com HMAC. Falhas voltam pelas filas de retry com TTL crescente e, esgotadas as tentativas, vão para a DLQ.

```mermaid
sequenceDiagram
    autonumber
    participant MQ as RabbitMQ
    participant EV as Consumidor notificacoes.eventos
    participant DB as Postgres Notificações
    participant WH as Consumidor notificacoes.webhooks
    participant REC as Receptor do webhook
    participant RT as Filas notificacoes.webhooks.retry.1 a 5
    participant DLQ as notificacoes.dlq

    MQ->>EV: evento de financeiro.eventos
    EV->>DB: inbox, uma notificação por assinatura ativa e tarefas no outbox
    DB->>MQ: tarefa.webhook para a fila notificacoes.webhooks
    MQ->>WH: tarefa de entrega
    WH->>WH: assina o corpo com HMAC SHA-256
    WH->>REC: POST com X-Assinatura, X-Assinatura-Timestamp, X-Evento-Id e X-Evento-Tipo

    alt Resposta 2xx
        REC-->>WH: 2xx
        WH->>DB: registra a entrega e marca a notificação como enviada
    else Falha: fora de 2xx, timeout de 5 s ou erro de rede
        REC--xWH: falha
        WH->>DB: registra a tentativa
        WH->>RT: publica na fila retry.N, com N de 1 a 5
        Note over RT: o TTL expira e a mensagem volta para notificacoes.webhooks
        RT-->>MQ: dead-letter para notificacoes.webhooks
        MQ->>WH: nova tentativa
    end

    Note over WH,DLQ: na 6ª falha a notificação vira falhou e a mensagem vai para a DLQ
    WH->>DLQ: publica em notificacoes.dlq
```

Os TTLs padrão das filas de retry são 1 s, 5 s, 30 s, 2 min e 10 min. A entrega é pelo menos uma vez, então o receptor deve deduplicar por `X-Evento-Id`.
