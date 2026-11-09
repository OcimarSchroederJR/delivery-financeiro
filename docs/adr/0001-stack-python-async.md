# ADR 0001: Stack Python assíncrona

- **Status:** aceita

## Contexto

Pagamentos, Notificações e Avaliações passam a maior parte do tempo esperando I/O: banco, broker, HTTP das outras equipes e SMTP. A produção roda numa VM de 4 GB que também hospeda 3 Postgres, RabbitMQ, Jaeger, Mailpit, Caddy e 6 processos Python (3 APIs e 3 workers). Além disso, a disciplina e o livro *Architecture Patterns with Python* usam Python nos exemplos.

## Decisão

Python 3.12, FastAPI + Pydantic v2, SQLAlchemy 2.0 async com asyncpg, Alembic e FastStream para o RabbitMQ. Tipagem verificada com `mypy --strict` e dependências gerenciadas por um workspace uv.

O FastAPI gera o OpenAPI e o FastStream gera o AsyncAPI a partir do código, então o contrato publicado não diverge da implementação.

## Alternativas consideradas

- **Go:** menos memória por processo, mas a equipe não tem prática, não há equivalente direto ao FastStream/AsyncAPI e o material da disciplina não ajudaria.
- **Spring Boot:** maduro, mas o consumo de memória da JVM pesaria com 6 processos de aplicação numa VM de 4 GB.
- **NestJS:** bom ajuste para I/O, mas sem o livro de referência em Python e sem o mesmo ganho de contratos gerados.

## Consequências

- Um só idioma para API, worker, testes e mocks; o código técnico comum cabe numa lib (ADR 0007).
- O GIL não importa para trabalho de I/O, e não há processamento de CPU pesado nestes serviços.
- Código síncrono bloqueante dentro do laço de eventos derruba a latência; por isso tudo que toca banco ou rede é `async`.
- Para caber em 4 GB, a VM é provisionada com swap de 2 GB.

**Onde está no código:** `libs/plataforma/pyproject.toml` (dependências), `pyproject.toml` (workspace uv), `services/pagamentos/Dockerfile` (`python:3.12-slim`), `libs/plataforma/src/plataforma/mensageria.py` (FastStream), `infra/cloud-init.yaml` (swap).
