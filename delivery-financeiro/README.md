# delivery-financeiro

Monorepo do grupo **Financeiro e Pós** (Equipe 3, Sessão 3) da disciplina de Integração de Sistemas — Plataforma de Delivery.

Este grupo é responsável por 2 dos 3 serviços da equipe: **Pagamentos** e **Notificações**. O serviço de **Avaliações** também está incluído no scaffold por completude da divisão de domínios, mas está fora do escopo desta equipe.

> **Importante:** este repositório contém apenas a estrutura inicial (scaffold) dos serviços — projetos NestJS prontos para rodar, Docker, testes de health-check e documentação Swagger vazia. A lógica de negócio de cada endpoint será implementada ao longo da disciplina.

## Estrutura

```
delivery-financeiro/
├── services/
│   ├── pagamentos/      # porta 8051
│   ├── notificacoes/    # porta 8052
│   └── avaliacoes/      # porta 8053
├── docker-compose.yml   # sobe os 3 serviços juntos
└── README.md
```

Cada serviço é um projeto NestJS + TypeScript independente, com seu próprio `package.json`, `Dockerfile`, `docker-compose.yml` (para rodar isolado) e README.

## Como rodar tudo com um único comando

```bash
cp .env.example .env
docker compose up --build
```

Isso sobe os 3 serviços e os 3 bancos de dados PostgreSQL (um por serviço, isolados), todos na mesma rede Docker (`delivery-financeiro-net`) para comunicação interna:

| Serviço       | Porta | Swagger                          |
|---------------|-------|-----------------------------------|
| Pagamentos    | 8051  | http://localhost:8051/docs        |
| Notificações  | 8052  | http://localhost:8052/docs        |
| Avaliações    | 8053  | http://localhost:8053/docs        |

## Como rodar um serviço isolado

Cada serviço também tem seu próprio `docker-compose.yml`. Veja o README de cada um:

- [services/pagamentos/README.md](services/pagamentos/README.md)
- [services/notificacoes/README.md](services/notificacoes/README.md)
- [services/avaliacoes/README.md](services/avaliacoes/README.md)

## Regras de integração (válidas para todos os serviços)

- **Banco de dados por serviço**: proibido cruzamento de dados (JOINs) no banco de outro grupo. Comunicação entre serviços é sempre via HTTP.
- **Valores financeiros**: sempre inteiros representando centavos (nunca ponto flutuante).
- **Datas**: sempre ISO 8601 (ex: `2026-08-24T14:30:00Z`).
- **Erros**: formato padrão `{"erro": true, "mensagem": "Detalhes da falha"}`, com o código HTTP correto.
- **Resiliência**: se uma dependência externa (outro serviço) estiver fora do ar, a resposta deve ser um erro amigável — o processo nunca pode crashar.
- **Cobertura de testes**: mínimo de 75%.

## Stack

- NestJS + TypeScript
- TypeORM + PostgreSQL (um banco por serviço)
- Swagger / OpenAPI
- Jest + Supertest
- Docker / Docker Compose
