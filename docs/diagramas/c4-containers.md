# C4: diagrama de containers

Os três serviços da Equipe 5 têm cada um uma API, um worker e um banco PostgreSQL próprio. Os eventos trafegam pelo exchange `financeiro.eventos` do RabbitMQ. Em produção, o Caddy é o único ponto de entrada (portas 80 e 443).

```mermaid
flowchart TB
    usuarios["Clientes, admin e outras equipes"]

    subgraph borda["Borda - somente em produção"]
        caddy["Caddy<br/>HTTPS e roteamento por caminho"]
    end

    subgraph pag["Pagamentos"]
        pag_api["API pagamentos<br/>porta 8013"]
        pag_worker["Worker pagamentos<br/>relay do outbox"]
        pag_db[("Postgres db-pagamentos")]
    end

    subgraph noti["Notificações"]
        not_api["API notificacoes<br/>porta 8014"]
        not_worker["Worker notificacoes<br/>consumidores e entrega"]
        not_db[("Postgres db-notificacoes")]
    end

    subgraph ava["Avaliações"]
        ava_api["API avaliacoes<br/>porta 8015"]
        ava_worker["Worker avaliacoes<br/>relay e retentativa de estornos"]
        ava_db[("Postgres db-avaliacoes")]
    end

    subgraph infra["Infraestrutura"]
        rabbit["RabbitMQ<br/>exchange financeiro.eventos<br/>portas 5672 e 15672"]
        mailpit["Mailpit<br/>SMTP 1025 e painel 8025"]
        jaeger["Jaeger<br/>OTLP 4318 e painel 16686"]
    end

    usuarios -->|"HTTPS"| caddy
    caddy -->|"/pagamentos"| pag_api
    caddy -->|"/notificacoes"| not_api
    caddy -->|"/avaliacoes"| ava_api
    caddy -->|"/jaeger"| jaeger
    caddy -->|"/mailpit"| mailpit

    pag_api --> pag_db
    pag_worker --> pag_db
    not_api --> not_db
    not_worker --> not_db
    ava_api --> ava_db
    ava_worker --> ava_db

    pag_worker -->|"publica eventos"| rabbit
    ava_worker -->|"publica eventos"| rabbit
    not_worker -->|"publica eventos externos e tarefas"| rabbit
    rabbit -->|"fila notificacoes.eventos"| not_worker

    ava_api -->|"POST /v1/pagamentos/id/estornos"| pag_api
    ava_worker -->|"retentativa do estorno"| pag_api
    not_worker -->|"SMTP"| mailpit

    pag_api -.->|"traces"| jaeger
    not_api -.->|"traces"| jaeger
    ava_api -.->|"traces"| jaeger
```

Localmente (`compose.yaml`) não há Caddy: as APIs, o RabbitMQ, o Mailpit e o Jaeger publicam suas portas direto no host.
