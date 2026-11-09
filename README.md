# delivery-financeiro — Equipe 5 (Financeiro e Pós)

Serviços de **Pagamentos**, **Notificações** e **Avaliações** da Plataforma de Delivery
(Integração de Sistemas — UPE Garanhuns). A especificação completa está em
[`docs/arquitetura/especificacao.md`](docs/arquitetura/especificacao.md).

> **Estado:** Fases 1 a 5 da [especificação](docs/arquitetura/especificacao.md) (§11) concluídas.
> Os três serviços estão completos, com testes e contratos: Pagamentos (aprovação, recusa, antifraude,
> Pix, estornos), Notificações (e-mail, webhooks, `POST /v1/eventos`) e Avaliações (avaliações,
> disputas e saga de estorno). Também existem a `libs/plataforma`, os mocks das Equipes 1, 3 e 4,
> o CI (lint, tipos, testes, cobertura mínima de 75%, contratos, e2e com Newman e schemathesis),
> a coleção Postman, os ADRs, os diagramas e o guia de integração.
> A infraestrutura de produção (VM, Caddy, CD) está pronta, mas o deploy ainda não foi feito (Fase 6).
> Os manifests k8s (Fase 7, bônus) não existem.

## Equipe

Luiz Tenório · João Gabriel · Alana Brito · Ocimar Schroeder

## Serviços

| Serviço | Camada | O que faz | Quem consome | Porta | Swagger | AsyncAPI |
|---|---|---|---|---|---|---|
| Pagamentos | Entidade | autoriza pagamentos de pedidos (cartão e Pix), antifraude e estornos; publica `pagamento.aprovado`, `pagamento.recusado` e `pagamento.estornado` | Eq. 3 (checkout) e Avaliações (estorno da disputa) | 8013 | http://localhost:8013/docs | [`pagamentos.json`](docs/asyncapi/pagamentos.json) |
| Notificações | Utilitário | consome os eventos e envia e-mail e webhooks, com retry e DLQ; recebe eventos externos em `POST /v1/eventos` | qualquer equipe (webhooks e `/v1/eventos`); Eq. 4 (entrega concluída) | 8014 | http://localhost:8014/docs | [`notificacoes.json`](docs/asyncapi/notificacoes.json) |
| Avaliações | Entidade + Tarefa | avaliação por pedido entregue, resumo do restaurante, disputas e saga de estorno; publica `avaliacao.registrada` e `disputa.*` | clientes e admin | 8015 | http://localhost:8015/docs | [`avaliacoes.json`](docs/asyncapi/avaliacoes.json) |

Cada serviço sobe 4 containers: a API (`pagamentos`, `notificacoes`, `avaliacoes`), o worker
(`pagamentos-worker`, `notificacoes-worker`, `avaliacoes-worker`), o banco PostgreSQL próprio
(`db-<serviço>`) e a migração (`migrate-<serviço>`, roda e termina). O AsyncAPI é um arquivo,
não uma página servida; o OpenAPI de cada serviço está em [`docs/openapi/`](docs/openapi/).

Documentação:

- [Especificação](docs/arquitetura/especificacao.md) e [levantamento de requisitos](docs/levantamento-requisitos.md)
- [ADRs](docs/adr/README.md): as 10 decisões de arquitetura e seus trade-offs
- [Diagramas](docs/diagramas/README.md): mapa de integração, fluxos, C4, sequências e estados
- [Guia de integração](docs/guia-de-integracao.md): para as outras equipes chamarem os serviços, publicarem eventos e validarem webhooks
- [Coleção Postman](docs/postman/delivery-financeiro.postman_collection.json) e [roteiro da demonstração](docs/roteiro-demo.md)
- Contratos: [`docs/openapi/`](docs/openapi/) e [`docs/asyncapi/`](docs/asyncapi/)

## Como rodar

Pré-requisito: Docker.

```bash
cp .env.example .env                              # opcional
docker compose --profile mocks up -d --build      # serviços + infraestrutura + mocks
docker compose --profile mocks down -v            # derruba tudo
```

O profile `mocks` sobe os stubs das Equipes 1 (identidade), 3 (pedidos) e 4 (logística), então o
fluxo completo roda sem depender das outras equipes. Sem o profile, sobem só os serviços e a
infraestrutura. Acompanhe os logs com `docker compose logs -f pagamentos notificacoes-worker avaliacoes`
e confira `docker compose ps` até os serviços ficarem `healthy`.

| Ferramenta | URL |
|---|---|
| RabbitMQ (guest/guest) | http://localhost:15672 |
| Mailpit | http://localhost:8025 |
| Jaeger | http://localhost:16686 |
| Mock Identidade (Eq. 1) | http://localhost:8001/docs |
| Mock Pedidos (Eq. 3) | http://localhost:8008/docs |
| Mock Logística (Eq. 4) | http://localhost:8010/docs |

Token de teste: `curl -X POST localhost:8001/tokens -H 'Content-Type: application/json' -d '{"sub":"cliente-1","papel":"cliente"}'`.

A coleção Postman com o fluxo completo da demo fica em [`docs/postman/`](docs/postman/). Para rodar
no terminal (o passo a passo para apresentar está no [roteiro da demonstração](docs/roteiro-demo.md)): `npx newman run docs/postman/delivery-financeiro.postman_collection.json -e docs/postman/local.postman_environment.json`.

### Produção

> **URLs de produção: a preencher depois do deploy.** O deploy ainda não foi feito; quando a VM
> existir, troque `<ip>` abaixo pelo IP real e registre aqui o endereço final.

A produção roda numa VM do Azure for Students, com `infra/compose.prod.yaml` e o Caddy na frente
(HTTPS automático). Domínio: `financeiro-eq5.<ip>.sslip.io` (o IP sai do `infra/azure/criar-vm.sh`).

| O quê | URL pública |
|---|---|
| Swagger de Pagamentos | `https://financeiro-eq5.<ip>.sslip.io/pagamentos/docs` |
| Swagger de Notificações | `https://financeiro-eq5.<ip>.sslip.io/notificacoes/docs` |
| Swagger de Avaliações | `https://financeiro-eq5.<ip>.sslip.io/avaliacoes/docs` |
| Readiness | `https://financeiro-eq5.<ip>.sslip.io/<servico>/saude/pronto` |
| Jaeger e Mailpit (basic auth) | `https://financeiro-eq5.<ip>.sslip.io/jaeger/` e `/mailpit/` |

- Para criar a VM, cadastrar os segredos e fazer o deploy, veja [`docs/deploy.md`](docs/deploy.md).
- Para testar a pilha de produção na sua máquina (`https://localhost/pagamentos/docs`), veja
  [`infra/README.md`](infra/README.md).

## Desenvolvimento

Pré-requisitos: [uv](https://docs.astral.sh/uv/) 0.11 e Docker (para os testes de integração).

```bash
uv python install 3.12
uv sync
uv run pre-commit install
uv run pytest                                 # todos os testes (integração usa Docker)
uv run pytest -m "not integracao"             # sem Docker
uv run pytest services/pagamentos/tests --cov=pagamentos   # um serviço, com cobertura
uv run python -m pagamentos.contratos         # regenera docs/openapi e docs/asyncapi
```

## Estrutura

```
libs/plataforma/   código técnico compartilhado (erros, logs, auth, outbox, inbox, HTTP...)
services/<s>/      um serviço: src/<s>/{dominio,aplicacao,adaptadores}, alembic/, tests/
mocks/             stubs das Equipes 1, 3 e 4 (profile "mocks")
infra/             produção: compose.prod.yaml, Caddyfile (HTTPS), cloud-init e criação da VM
docs/              especificação, levantamento de requisitos e contratos
```

## Contribuição

- Uma branch por tarefa a partir de `dev`: `feat/...`, `fix/...`, `refactor/...`, `chore/...`.
- Commits em português: `tipo(escopo): descrição` (ex.: `feat(pagamentos): adiciona estorno parcial`).
- PR para `dev`; o CI precisa passar (`ci-ok`).
