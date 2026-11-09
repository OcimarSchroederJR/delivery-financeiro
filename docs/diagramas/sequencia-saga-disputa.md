# Sequência: saga de estorno da disputa

O admin decide a disputa com `PATCH /v1/disputas/{id}`. Se for procedente, Avaliações grava `estorno_pendente` e pede o estorno a Pagamentos com token de serviço e `Idempotency-Key: disputa-{id}`. Repetir o pedido é seguro, e o resultado define o desfecho em um de três ramos.

```mermaid
sequenceDiagram
    autonumber
    participant ADM as Admin
    participant AVA as API Avaliações
    participant DB as Postgres Avaliações
    participant PAG as API Pagamentos
    participant WK as Worker Avaliações
    participant MQ as RabbitMQ

    ADM->>AVA: PATCH /v1/disputas/{id} com status procedente
    AVA->>DB: grava estorno_pendente
    AVA->>PAG: POST /v1/pagamentos/{id}/estornos com token de serviço e Idempotency-Key disputa-{id}

    alt Sucesso
        PAG-->>AVA: 201 estorno criado
        AVA->>DB: grava resolvida e evento disputa.resolvida no outbox
        AVA-->>ADM: 200 com a disputa resolvida
        WK->>MQ: publica disputa.resolvida
    else Falha transitória
        PAG--xAVA: timeout, 5xx ou chave em processamento
        AVA-->>ADM: 202 com a disputa em estorno_pendente
        loop até esgotar as tentativas, com backoff exponencial
            WK->>DB: reserva disputas pendentes vencidas
            WK->>PAG: repete o POST com a mesma Idempotency-Key
        end
        Note over WK,DB: se esgotar, vira estorno_falhou com motivo RESULTADO_INCERTO
    else Falha definitiva
        PAG-->>AVA: recusa com código de erro, por exemplo PAGAMENTO_NAO_ESTORNAVEL
        AVA->>DB: grava estorno_falhou com o código da recusa e evento no outbox
        AVA-->>ADM: 200 com a disputa em estorno_falhou
        WK->>MQ: publica disputa.estorno_falhou
    end
```

Quando as tentativas se esgotam com falha transitória, o motivo é `RESULTADO_INCERTO`: o estorno pode ter sido feito em Pagamentos, e o admin deve conferir lá antes de agir. O evento `disputa.estorno_falhou` gera um e-mail de ação necessária ao admin.
