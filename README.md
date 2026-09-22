# delivery-financeiro

Monorepo do grupo **Financeiro e Pós** (Equipe 3, Sessão 3) na disciplina de Integração de Sistemas — Plataforma de Delivery (arquitetura de 15 microsserviços distribuídos entre 5 equipes).

Esta equipe é responsável por dois dos três serviços do grupo: **Pagamentos** e **Notificações**. O serviço de **Avaliações** está incluído no scaffold por completude da divisão de domínios, mas está fora do escopo desta equipe.

> O conteúdo do projeto está em [`delivery-financeiro/`](delivery-financeiro/). No momento o repositório contém apenas o **scaffold** dos serviços (projetos NestJS prontos para rodar, Docker, testes de health-check e Swagger vazio) — a lógica de negócio de cada endpoint será implementada ao longo da disciplina.

## Serviços

| Serviço | Porta | Descrição |
|---|---|---|
| [Pagamentos](delivery-financeiro/services/pagamentos) | 8051 | Processamento de transações financeiras de pedidos |
| [Notificações](delivery-financeiro/services/notificacoes) | 8052 | Envio de e-mails e disparo de webhooks de alerta |
| [Avaliações](delivery-financeiro/services/avaliacoes) | 8053 | Coleta de notas, comentários e gestão de disputas |

## Como rodar tudo com um único comando

```bash
cd delivery-financeiro
cp .env.example .env
docker compose up --build
```

Veja o [README do monorepo](delivery-financeiro/README.md) para detalhes de arquitetura, regras de integração e stack utilizada.

## Stack

NestJS + TypeScript · TypeORM + PostgreSQL (um banco por serviço) · Swagger/OpenAPI · Jest + Supertest · Docker / Docker Compose
