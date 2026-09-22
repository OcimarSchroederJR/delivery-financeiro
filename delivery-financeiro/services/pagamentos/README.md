# Serviço de Pagamentos

Responsável pelo processamento de transações financeiras de pedidos. Parte do grupo **Financeiro e Pós** (Equipe 3, Sessão 3).

Stack: NestJS + TypeScript, TypeORM + PostgreSQL, Swagger (OpenAPI), Jest.

> Este repositório contém apenas o **scaffold** do serviço (projeto NestJS inicial, Docker, testes de health-check). Os endpoints de domínio (`/pagamentos`, `/pagamentos/{id}`, `/pagamentos/{id}/estorno`) e as integrações com Identidade e Notificações serão implementados ao longo da disciplina.

## Como rodar isolado (com Docker)

```bash
cp .env.example .env
docker compose up --build
```

O serviço sobe em `http://localhost:8051` com seu próprio banco PostgreSQL isolado (container `pagamentos-db`).

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
http://localhost:8051/docs
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

- **Identidade** (`http://localhost:8011`): validação de token JWT do usuário.
- **Notificações** (`http://localhost:8052`): disparo de e-mail de confirmação após pagamento aprovado.
- Recebe chamadas da **Equipe 3 — Checkout** (`http://localhost:8031`).

Falhas de comunicação com serviços externos devem ser tratadas com erro amigável (`{"erro": true, "mensagem": "..."}`), sem derrubar o processo.
