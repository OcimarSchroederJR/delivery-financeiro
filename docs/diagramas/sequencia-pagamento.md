# Sequência: pagamento de um pedido

A Equipe 3 pede o pagamento com `Idempotency-Key`. Pagamentos confere o pedido, decide no gateway simulado e grava o resultado junto com o evento no outbox. O worker publica o evento, e Notificações o consome (inbox) e envia o e-mail.

```mermaid
sequenceDiagram
    autonumber
    participant E3 as Equipe 3 - Pedidos
    participant PAG as API Pagamentos
    participant GW as Gateway simulado
    participant DB as Postgres Pagamentos
    participant RL as Worker Pagamentos - relay
    participant MQ as RabbitMQ
    participant NOT as Worker Notificações
    participant E1 as Equipe 1 - Identidade
    participant SMTP as Servidor SMTP

    E3->>PAG: POST /v1/pagamentos com Idempotency-Key
    PAG->>E3: GET /pedidos/{id}
    E3-->>PAG: dados e valor do pedido
    PAG->>GW: autoriza o pagamento
    GW-->>PAG: aprovado ou recusado
    PAG->>DB: grava pagamento, chave de idempotência e evento no outbox
    PAG-->>E3: 201 com o pagamento ou 409 PAGAMENTO_RECUSADO
    RL->>DB: lê mensagens pendentes do outbox
    RL->>MQ: publica pagamento.aprovado ou pagamento.recusado em financeiro.eventos
    MQ->>NOT: entrega pela fila notificacoes.eventos
    NOT->>NOT: registra na inbox e agenda a tarefa de e-mail
    NOT->>E1: GET /perfis/{id}
    E1-->>NOT: e-mail do cliente
    NOT->>SMTP: envia o e-mail
```

Repetir a mesma `Idempotency-Key` com o mesmo corpo devolve a resposta gravada, sem cobrar duas vezes.
