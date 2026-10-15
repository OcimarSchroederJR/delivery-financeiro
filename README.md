# delivery-financeiro — Equipe 5 (Financeiro e Pós)

Serviços de **Pagamentos**, **Notificações** e **Avaliações** da Plataforma de Delivery
(Integração de Sistemas — UPE Garanhuns). A especificação completa está em
[`docs/arquitetura/especificacao.md`](docs/arquitetura/especificacao.md).

> **Estado:** Fase 1 (Fundação) concluída — biblioteca `libs/plataforma`, mocks das outras
> equipes, esqueleto dos 3 serviços, compose e CI. As regras de negócio chegam nas Fases 2 a 4.

## Equipe

Luiz Tenório · João Gabriel · Alana Brito · Ocimar Schroeder

## Serviços

| Serviço | Camada | Porta | Swagger |
|---|---|---|---|
| Pagamentos | Entidade | 8013 | http://localhost:8013/docs |
| Notificações | Utilitário | 8014 | http://localhost:8014/docs |
| Avaliações | Entidade + Tarefa | 8015 | http://localhost:8015/docs |

Contratos gerados: [`docs/openapi/`](docs/openapi/) e [`docs/asyncapi/`](docs/asyncapi/).

## Como rodar

Pré-requisito: Docker.

```bash
cp .env.example .env                              # opcional
docker compose --profile mocks up -d --build      # serviços + infraestrutura + mocks
docker compose --profile mocks down -v            # derruba tudo
```

| Ferramenta | URL |
|---|---|
| RabbitMQ (guest/guest) | http://localhost:15672 |
| Mailpit | http://localhost:8025 |
| Jaeger | http://localhost:16686 |
| Mock Identidade (Eq. 1) | http://localhost:8001/docs |
| Mock Pedidos (Eq. 3) | http://localhost:8008/docs |
| Mock Logística (Eq. 4) | http://localhost:8010/docs |

Token de teste: `curl -X POST localhost:8001/tokens -H 'Content-Type: application/json' -d '{"sub":"cliente-1","papel":"cliente"}'`.

## Desenvolvimento

Pré-requisitos: [uv](https://docs.astral.sh/uv/) 0.11 e Docker (para os testes de integração).

```bash
uv python install 3.12
uv sync
uv run pre-commit install
uv run pytest                                 # todos os testes
uv run pytest -m "not integracao"             # sem Docker
uv run pytest services/pagamentos/tests --cov=pagamentos
uv run python -m pagamentos.contratos         # regenera docs/openapi e docs/asyncapi
```

## Estrutura

```
libs/plataforma/   código técnico compartilhado (erros, logs, auth, outbox, inbox, HTTP...)
services/<s>/      um serviço: src/<s>/{dominio,aplicacao,adaptadores}, alembic/, tests/
mocks/             stubs das Equipes 1, 3 e 4 (profile "mocks")
docs/              especificação, levantamento de requisitos e contratos
```

## Contribuição

- Uma branch por tarefa a partir de `dev`: `feat/...`, `fix/...`, `refactor/...`, `chore/...`.
- Commits em português: `tipo(escopo): descrição` (ex.: `feat(pagamentos): adiciona estorno parcial`).
- PR para `dev`; o CI precisa passar (`ci-ok`).
