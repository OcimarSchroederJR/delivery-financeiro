# Serviço de Notificações

Responsável pelo envio de e-mails e disparo de webhooks de alerta. Parte do grupo **Financeiro e Pós** (Equipe 3, Sessão 3).

Stack: NestJS + TypeScript, TypeORM + PostgreSQL, Swagger (OpenAPI), Jest.

> Este repositório contém apenas o **scaffold** do serviço (projeto NestJS inicial, Docker, testes de health-check). Os endpoints de domínio (`/notificacoes/email`, `/notificacoes/webhook`, `/notificacoes/{id}`) e as integrações com Identidade, Pagamentos e Checkout serão implementados ao longo da disciplina.

## Como rodar isolado (com Docker)

```bash
cp .env.example .env
docker compose up --build
```

O serviço sobe em `http://localhost:8052` com seu próprio banco PostgreSQL isolado (container `notificacoes-db`).

## Como rodar localmente (sem Docker)

Pré-requisito: um PostgreSQL acessível com as credenciais definidas em `.env`.

```bash
cp .env.example .env
npm install
npm run start:dev
```

## Documentação da API

Com o serviço rodando, o Swagger UI fica disponível em:

```
http://localhost:8052/docs
```

## Testes

```bash
npm run test        # testes unitários
npm run test:e2e     # testes end-to-end (requer banco de dados disponível)
npm run test:cov     # testes com relatório de cobertura (mínimo exigido: 75%)
```

## Variáveis de ambiente

Veja [.env.example](.env.example).

## Integrações previstas

- **Identidade** (`http://localhost:8011`): busca do e-mail do usuário.
- **Pagamentos** e **Equipe 3 — Checkout** (`http://localhost:8031`): acionam o disparo de notificações internamente.
- Retry automático (mínimo 2 tentativas) em caso de falha no envio.

Falhas de comunicação com serviços externos devem ser tratadas com erro amigável (`{"erro": true, "mensagem": "..."}`), sem derrubar o processo.
