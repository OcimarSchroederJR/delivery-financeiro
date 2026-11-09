# Registros de decisões de arquitetura (ADR)

Cada arquivo registra uma decisão no formato Contexto, Decisão, Alternativas consideradas e Consequências, com a linha "Onde está no código" apontando para os arquivos que a implementam. A visão geral está em `docs/arquitetura/especificacao.md`.

| ADR | Decisão |
|---|---|
| [0001](0001-stack-python-async.md) | Stack Python assíncrona (FastAPI, SQLAlchemy async, FastStream) |
| [0002](0002-arquitetura-hexagonal.md) | Arquitetura hexagonal com Repository e Unit of Work |
| [0003](0003-sincrono-vs-assincrono.md) | HTTP quando precisa da resposta, RabbitMQ para efeitos colaterais; eventos externos por `POST /v1/eventos` |
| [0004](0004-rabbitmq-topic-retry-dlq.md) | Exchange topic, retry por TTL e DLQ |
| [0005](0005-outbox-e-inbox.md) | Transactional Outbox e Inbox |
| [0006](0006-idempotency-key.md) | `Idempotency-Key` com reserva por dono e lock por pedido |
| [0007](0007-libs-plataforma-compartilhada.md) | `libs/plataforma` compartilhada, só código técnico |
| [0008](0008-jwt-jwks-e-token-de-servico.md) | JWT via JWKS em cache e token de serviço interno |
| [0009](0009-deploy-vm-unica-vs-paas.md) | Deploy em VM única com Compose vs PaaS |
| [0010](0010-o-que-nao-usamos.md) | Tecnologias avaliadas e não adotadas |
