# Levantamento de Requisitos — Financeiro e Pós

**Projeto:** Plataforma de Delivery — Integração de Sistemas
**Grupo:** Equipe 5 (Financeiro e Pós)
**Versão:** 02.00
**Data:** 09/11/2026
**Identificador do documento:** LR-FIN
**Localização:** `delivery-financeiro/docs/levantamento-requisitos.md`

> **Numeração da equipe a confirmar com o professor.** A versão 01.00 deste documento usava "Equipe 3 — Sessão 3"; o README e a especificação de design usam "Equipe 5". Até a confirmação, este documento segue o README e a especificação ("Equipe 5"). Nas referências às outras equipes, vale a numeração da especificação: Equipe 1 (Identidade), Equipe 3 (Checkout/Pedidos) e Equipe 4 (Logística).

## Histórico de revisões

| Versão | Data | Autores | Descrição |
|---|---|---|---|
| 01.00 | 22/09/2026 | Luiz Tenório, João Gabriel, Alana Brito, Ocimar Schroeder | Versão inicial do levantamento de requisitos dos serviços de Pagamentos, Notificações e Avaliações |
| 02.00 | 09/11/2026 | Luiz Tenório, João Gabriel, Alana Brito, Ocimar Schroeder | Alinhamento aos contratos implementados (`docs/openapi/`, `docs/asyncapi/`): rotas `/v1`, estorno e disputa como recursos, eventos e webhooks, idempotência, outbox/inbox, retry com DLQ e formato de erro; numeração da equipe; seção de rastreabilidade |

## Equipe

| Nome |
|---|
| Luiz Tenório |
| João Gabriel |
| Alana Brito |
| Ocimar Schroeder |

---

## Índice

1. [Introdução](#1-introdução)
2. [Visão Geral do Produto](#2-visão-geral-do-produto)
3. [Fronteiras dos Serviços](#3-fronteiras-dos-serviços)
4. [Premissas e Restrições](#4-premissas-e-restrições)
5. [Requisitos Funcionais](#5-requisitos-funcionais)
6. [Requisitos Não Funcionais](#6-requisitos-não-funcionais)
7. [Requisitos de Integração](#7-requisitos-de-integração)
8. [Casos de Uso](#8-casos-de-uso)
9. [Gerência de Requisitos](#9-gerência-de-requisitos)
10. [Rastreabilidade: história, rota e PR](#10-rastreabilidade-história-rota-e-pr)

---

## 1. Introdução

### 1.1. Propósito

Este documento especifica os requisitos dos serviços de **Pagamentos**, **Notificações** e **Avaliações**, sob responsabilidade da Equipe 5 (Financeiro e Pós) na disciplina de Integração de Sistemas. Ele serve como referência para o desenvolvimento, testes e integração desses serviços com os demais 12 microsserviços da Plataforma de Delivery.

### 1.2. Público-alvo

Este documento é destinado aos integrantes da equipe responsável pelos serviços aqui descritos, às demais equipes da disciplina que consomem ou são consumidas por esses serviços (Identidade, Checkout/Pedidos, Logística), e ao professor responsável pela avaliação do projeto.

### 1.3. Escopo

Este documento trata exclusivamente dos 3 serviços sob responsabilidade da Equipe 5:

- **Pagamentos** (porta local 8013): autorização de pagamentos de pedidos (cartão e Pix), antifraude e estornos.
- **Notificações** (porta local 8014): consumo de eventos, envio de e-mails e entrega de webhooks por inscrição.
- **Avaliações** (porta local 8015): avaliações de pedidos entregues, resumo por restaurante e disputas com saga de estorno.

Os contratos implementados estão em `docs/openapi/` (HTTP) e `docs/asyncapi/` (eventos), e o desenho completo em [`docs/arquitetura/especificacao.md`](arquitetura/especificacao.md). Em caso de divergência, vale o OpenAPI.

Não fazem parte do escopo deste documento os requisitos dos demais 12 serviços da plataforma (Identidade, Catálogo, Checkout, Logística), que são de responsabilidade de outras equipes e documentados separadamente por elas.

### 1.4. Definições e Abreviações

| Termo | Definição |
|---|---|
| JWT | JSON Web Token, usado para autenticação entre serviços |
| JWKS | Conjunto de chaves públicas publicado pela Identidade, usado para validar o JWT localmente |
| Outbox | Evento gravado na mesma transação da mudança de estado e publicado depois por um relay |
| Inbox | Registro do `mensagem_id` já processado, para o consumidor ignorar mensagens repetidas |
| DLQ | Dead-letter queue: fila das mensagens que esgotaram as tentativas |
| RN | Regra de Negócio |
| CA | Critério de Aceite |
| US | User Story |
| RF | Requisito Funcional |
| RNF | Requisito Não Funcional |
| RI | Requisito de Integração |

### 1.5. Referências

- Documento de arquitetura de integração da disciplina: *Plataforma de Delivery — Arquitetura de Integração (15 Serviços)*.
- Especificação de design da Equipe 5: [`docs/arquitetura/especificacao.md`](arquitetura/especificacao.md), seções 3 e 4.
- Contratos HTTP: `docs/openapi/pagamentos.json`, `docs/openapi/notificacoes.json` e `docs/openapi/avaliacoes.json`.
- Contratos de eventos: `docs/asyncapi/pagamentos.json`, `docs/asyncapi/notificacoes.json` e `docs/asyncapi/avaliacoes.json`.
- [Guia de integração](guia-de-integracao.md) para as outras equipes.

### 1.6. Visão geral do documento

- Na seção 2 é apresentada uma visão geral dos serviços, seu contexto dentro da plataforma e seus consumidores.
- A seção 3 define as fronteiras de cada serviço: o que entra, o que sai, de quem e para quem.
- A seção 4 especifica as premissas e restrições do projeto.
- A seção 5 enumera os requisitos funcionais.
- A seção 6 enumera os requisitos não funcionais.
- A seção 7 detalha os requisitos de integração entre serviços.
- A seção 8 apresenta os principais casos de uso.
- A seção 9 traz a matriz de gerência dos requisitos.
- A seção 10 traz a tabela de rastreabilidade entre história, rota e PR.

---

## 2. Visão Geral do Produto

### 2.1. Contexto

A Plataforma de Delivery é composta por 15 microsserviços independentes, divididos entre 5 equipes, sem banco de dados compartilhado e sem comunicação em memória. A integração com as outras equipes ocorre via HTTP. A Equipe 5 (Financeiro e Pós) é responsável pela etapa de **fechamento do ciclo do pedido**: cobrar o cliente, avisá-lo sobre o andamento e coletar sua avaliação após a entrega.

### 2.2. Escopo do grupo Financeiro e Pós

| Serviço | Responsabilidade |
|---|---|
| Pagamentos | Autorizar, consultar e estornar (total ou parcialmente) pagamentos de pedidos |
| Notificações | Reagir a eventos: enviar e-mails e entregar webhooks a sistemas inscritos |
| Avaliações | Coletar notas e comentários de pedidos entregues e gerenciar disputas, com estorno automático quando procedentes |

### 2.3. Descrição dos consumidores (atores)

Diferente de um sistema com usuários finais diretos, os "usuários" destes serviços são majoritariamente **outros microsserviços da plataforma**:

- **Equipe 3 — Checkout/Pedidos** (endereço real a alinhar, issue #39): chama `POST /v1/pagamentos`, publica eventos `pedido.*` em `POST /v1/eventos` e é consultada por Pagamentos e Avaliações em `GET /pedidos/{id}`.
- **Equipe 4 — Logística** (endereço real a alinhar, issue #39): publica eventos `entrega.*` em `POST /v1/eventos`.
- **Equipe 1 — Identidade** (endereço real a alinhar, issue #38): emite os tokens JWT (validados localmente via JWKS) e fornece o e-mail do usuário em `GET /perfis/{id}`.
- **Cliente** (usuário final): é impactado pelos efeitos destes serviços (cobrança, e-mail recebido) e usa as rotas de avaliação e disputa por meio de um front-end mantido por outra equipe, com o token emitido pela Identidade.
- **Administrador** (papel `admin` do token): resolve disputas e vê todas as inscrições de webhook e notificações.
- **Serviço interno**: os workers da própria equipe usam um token de serviço (papel `servico`), aceito apenas nas rotas de estorno e de listagem de pagamentos.
- **Professor**: valida o funcionamento via Postman/Insomnia e observa os logs de integração no terminal.

Enquanto o alinhamento das issues #38 e #39 não termina, o ambiente local usa os mocks do profile `mocks` do compose: Identidade em `localhost:8001`, Pedidos em `localhost:8008` e Logística em `localhost:8010`.

---

## 3. Fronteiras dos Serviços

Esta seção define explicitamente o que **entra** e o que **sai** de cada serviço, delimitando sua responsabilidade dentro da integração.

### 3.1. Pagamentos

| Direção | Dado / Evento | De quem → Para quem | Protocolo |
|---|---|---|---|
| Entrada | `POST /v1/pagamentos` com `pedido_id`, `metodo` (`cartao_credito` ou `pix`) e `cartao` (só para cartão), com `Idempotency-Key`. O valor não vem no corpo: é lido do pedido | Checkout (Eq. 3) → Pagamentos | HTTP/REST (JSON) |
| Entrada | Token JWT (`Authorization: Bearer`), validado localmente com a chave pública (JWKS) da Identidade | Checkout → Pagamentos (chave obtida da Identidade, Eq. 1) | HTTP/REST (Bearer token) |
| Entrada | Consulta de pagamento: `GET /v1/pagamentos/{pagamento_id}` e `GET /v1/pagamentos?pedido_id=` | Checkout / Avaliações → Pagamentos | HTTP/REST |
| Entrada | Estorno total ou parcial: `POST /v1/pagamentos/{pagamento_id}/estornos` com `Idempotency-Key` | Avaliações (saga da disputa) / Checkout → Pagamentos | HTTP/REST |
| Entrada | Consulta do pedido (valor, dono e status): `GET /pedidos/{id}` | Pagamentos → Checkout (Eq. 3) | HTTP/REST |
| Saída | Resultado do pagamento: `201` aprovado ou `409 PAGAMENTO_RECUSADO` | Pagamentos → Checkout | HTTP/REST (resposta síncrona) |
| Saída | Eventos `pagamento.aprovado`, `pagamento.recusado` e `pagamento.estornado`, via outbox | Pagamentos → exchange `financeiro.eventos` → Notificações | RabbitMQ (AsyncAPI) |
| **Fora do escopo** | Cálculo de subtotal, aplicação de cupons, orquestração do pedido | — (é responsabilidade do Checkout; o valor cobrado vem do pedido) | — |
| **Fora do escopo** | Emissão de nota fiscal, integração com gateways de pagamento reais | — (o gateway é simulado, atrás da porta `GatewayDePagamento`) | — |

### 3.2. Notificações

| Direção | Dado / Evento | De quem → Para quem | Protocolo |
|---|---|---|---|
| Entrada | Eventos do domínio (`pagamento.*`, `avaliacao.*`, `disputa.*`) | Pagamentos / Avaliações → exchange `financeiro.eventos` → Notificações | RabbitMQ (AsyncAPI) |
| Entrada | Eventos externos (`pedido.*`, `entrega.*`) no envelope padrão, em `POST /v1/eventos` (resposta `202`) | Checkout (Eq. 3) / Logística (Eq. 4) → Notificações | HTTP/REST |
| Entrada | Inscrição de webhook: `POST /v1/webhooks` (`url` e lista de `eventos`); consulta e remoção em `GET /v1/webhooks` e `DELETE /v1/webhooks/{assinatura_id}` | Qualquer equipe → Notificações | HTTP/REST |
| Entrada | Consulta de e-mail do usuário: `GET /perfis/{id}` | Notificações → Identidade (Eq. 1) | HTTP/REST |
| Saída | Consulta de notificações em `GET /v1/notificacoes?destinatario_id=` e do histórico de entregas em `GET /v1/webhooks/{assinatura_id}/entregas` | Notificações → quem consultar | HTTP/REST |
| Saída | Entrega de webhook assinada (HMAC-SHA256), com retry e DLQ | Notificações → URL inscrita | HTTP/REST (POST) |
| Saída | E-mail enviado | Notificações → caixa de e-mail do usuário final | SMTP (Mailpit no ambiente local) |
| **Fora do escopo** | Regras de quando notificar no domínio de outras equipes | — (é decidido por quem publica o evento; Notificações valida só o envelope dos eventos externos) | — |

### 3.3. Avaliações

| Direção | Dado / Evento | De quem → Para quem | Protocolo |
|---|---|---|---|
| Entrada | Criação de avaliação: `POST /v1/avaliacoes` com `pedido_id`, `nota_restaurante`, `nota_entrega` (opcional) e `comentario` (opcional). O cliente vem do `sub` do token | Cliente (via front-end de outra equipe) → Avaliações | HTTP/REST |
| Entrada | Token JWT do usuário, validado localmente com a chave pública (JWKS) da Identidade | Cliente → Avaliações (chave obtida da Identidade, Eq. 1) | HTTP/REST (Bearer token) |
| Entrada | Consulta do pedido (existe, é do cliente e foi entregue): `GET /pedidos/{id}` | Avaliações → Checkout/Pedidos (Eq. 3) | HTTP/REST |
| Entrada | Abertura de disputa em `POST /v1/disputas`; decisão do admin em `PATCH /v1/disputas/{disputa_id}` | Cliente / admin → Avaliações | HTTP/REST |
| Entrada | Consulta do pagamento do pedido: `GET /v1/pagamentos?pedido_id=` | Avaliações → Pagamentos | HTTP/REST |
| Saída | Avaliações, resumo por restaurante e disputas: `GET /v1/avaliacoes`, `GET /v1/avaliacoes/{avaliacao_id}`, `GET /v1/resumos-avaliacoes/{restaurante_id}`, `GET /v1/disputas` e `GET /v1/disputas/{disputa_id}` | Avaliações → quem consultar (Checkout, front-end) | HTTP/REST |
| Saída | Estorno da disputa procedente: `POST /v1/pagamentos/{pagamento_id}/estornos` com `Idempotency-Key: disputa-{disputa_id}` | Avaliações → Pagamentos | HTTP/REST |
| Saída | Eventos `avaliacao.registrada`, `disputa.aberta`, `disputa.resolvida` e `disputa.estorno_falhou`, via outbox | Avaliações → exchange `financeiro.eventos` | RabbitMQ (AsyncAPI) |
| **Fora do escopo** | Moderação de conteúdo ofensivo | — (não especificado no escopo atual da disciplina) | — |

---

## 4. Premissas e Restrições

- Pressupõe-se que os integrantes da equipe tenham disponibilidade para desenvolver, testar e integrar os 3 serviços, seguindo o cronograma de ondas definido pela disciplina (Onda 3 — Financeiro só é ativado após um pedido ser gerado com sucesso pelo Checkout, Equipe 3).
- A stack adotada é Python 3.12 com FastAPI, PostgreSQL 16, RabbitMQ e Docker (especificação, seção 2). O scaffold NestJS previsto na versão 01.00 foi descartado.
- Cada serviço deve poder ser executado de forma isolada, sem depender da disponibilidade simultânea dos demais serviços da plataforma para subir (mas suas funcionalidades de integração dependerão deles em tempo de execução). Para isso o compose oferece os mocks das Equipes 1, 3 e 4 (`--profile mocks`).
- O banco de dados de cada serviço é isolado; é proibido acesso direto (JOIN) ao banco de outro serviço, mesmo dentro do próprio grupo Financeiro e Pós.
- A comunicação síncrona entre os serviços, e com as demais equipes, ocorre via HTTP. A mensageria (RabbitMQ) é interna à Equipe 5 e serve a efeitos colaterais (notificações e webhooks); as outras equipes entram por HTTP, em `POST /v1/eventos`, sem precisar conhecer o broker.
- Os endereços e portas das outras equipes **ainda dependem do alinhamento das issues #38 (Identidade) e #39 (Checkout e Logística)** e são configurados por variáveis de ambiente (`IDENTIDADE_URL`, `PEDIDOS_URL`, `JWKS_URL`).

---

## 5. Requisitos Funcionais

*Como um <serviço/ator>, eu quero <função>, de forma que <razão/benefício>.*

Todas as rotas têm o prefixo `/v1` (exceto `/saude/*`), exigem `Authorization: Bearer <jwt>` e seguem o contrato publicado em `docs/openapi/`. Listas são paginadas com `?pagina=1&tamanho=20` (máximo 100), no formato `{"itens": [...], "pagina": 1, "tamanho": 20, "total": 57}`.

### 5.1. Pagamentos

#### [US-PAG-001] Processar pagamento

Como o serviço de Checkout, eu quero solicitar o pagamento de um pedido, de forma que o cliente possa concluir a compra. Rota: `POST /v1/pagamentos`.

- [CA-PAG-01-01] A solicitação deve conter `pedido_id` e `metodo` (`cartao_credito` ou `pix`). Para cartão, deve conter também o bloco `cartao` (`numero`, `titular`, `validade`, `cvv`), que nunca é persistido nem logado (guarda-se apenas os 4 últimos dígitos).
- [CA-PAG-01-02] O valor não vem no corpo: é obtido do pedido em `GET /pedidos/{pedido_id}` (Equipe 3). O pedido deve pertencer ao `sub` do token quando o papel for `cliente` (`403` caso contrário).
- [CA-PAG-01-03] O cabeçalho `Idempotency-Key` é obrigatório (`400 IDEMPOTENCY_KEY_AUSENTE`). A mesma chave com o mesmo corpo devolve a resposta gravada; com corpo diferente, `422 IDEMPOTENCY_KEY_REUTILIZADA`; requisição concorrente com a mesma chave, `409 IDEMPOTENCY_EM_PROCESSAMENTO`. A chave vale por 24 h e respostas `5xx` não são gravadas.
- [CA-PAG-01-04] Pagamento aprovado retorna `201` com o identificador do pagamento. Pagamento recusado retorna `409 PAGAMENTO_RECUSADO`, a tentativa é persistida e o corpo traz `pagamento_id`.
- [CA-PAG-01-05] Só pode existir um pagamento aprovado por pedido (`409 PEDIDO_JA_PAGO`); pedido inexistente retorna `422 PEDIDO_INEXISTENTE`.
- [CA-PAG-01-06] Valor acima de 500000 centavos é recusado com motivo `analise_antifraude`.
- [CA-PAG-01-07] Ao aprovar, recusar ou estornar, o serviço grava o evento no outbox (`pagamento.aprovado`, `pagamento.recusado`, `pagamento.estornado`). Pagamentos não chama Notificações diretamente; Notificações reage ao evento.
- [CA-PAG-01-08] Se o pedido (Equipe 3) ou o gateway estiver indisponível, a resposta é `503 DEPENDENCIA_INDISPONIVEL`, sem persistir aprovação.

#### [US-PAG-002] Consultar pagamento

Como o serviço de Checkout (ou outro consumidor autorizado), eu quero consultar um pagamento, de forma que eu possa saber se o pagamento de um pedido foi concluído. Rotas: `GET /v1/pagamentos/{pagamento_id}` e `GET /v1/pagamentos?pedido_id=`.

- [CA-PAG-02-01] A consulta individual é feita pelo identificador do pagamento; a listagem filtra por `pedido_id` na query string e é paginada.
- [CA-PAG-02-02] Se o pagamento não existir, o sistema deve retornar `404` no formato padrão de erro.
- [CA-PAG-02-03] A resposta informa o `status` (`aprovado`, `parcialmente_estornado`, `estornado` ou `recusado`) e o saldo estornável em centavos.

#### [US-PAG-003] Estornar pagamento

Como o serviço de Avaliações (saga da disputa) ou o Checkout, eu quero estornar um pagamento aprovado, total ou parcialmente, de forma que o cliente seja reembolsado. O estorno é um sub-recurso do pagamento. Rotas: `POST /v1/pagamentos/{pagamento_id}/estornos` e `GET /v1/pagamentos/{pagamento_id}/estornos`.

- [CA-PAG-03-01] O corpo traz `valor_centavos` e `motivo`; se `valor_centavos` vier ausente, estorna-se o saldo estornável inteiro. `Idempotency-Key` é obrigatório.
- [CA-PAG-03-02] Pagamento recusado ou já totalmente estornado retorna `409 PAGAMENTO_NAO_ESTORNAVEL`; valor acima do saldo retorna `422 VALOR_EXCEDE_SALDO_ESTORNAVEL`.
- [CA-PAG-03-03] O estorno parcial leva o pagamento a `parcialmente_estornado`; o estorno do restante, a `estornado`.
- [CA-PAG-03-04] Esta rota aceita também o token de serviço interno (papel `servico`), usado pelo worker da saga de disputa.
- [CA-PAG-03-05] Pagamento inexistente retorna `404`. A lista de estornos do pagamento é consultada em `GET /v1/pagamentos/{pagamento_id}/estornos`.

### 5.2. Notificações

As notificações são disparadas por **eventos**, não por pedidos de envio de e-mail feitos por outros serviços.

#### [US-NOT-001] Enviar e-mail a partir de eventos

Como o ecossistema de serviços, eu quero que um evento de negócio (ex.: `pagamento.aprovado`) resulte em e-mail ao cliente, de forma que ele seja informado sobre o andamento do seu pedido. Eventos externos entram por `POST /v1/eventos`; eventos de Pagamentos e Avaliações chegam pelo broker.

- [CA-NOT-01-01] `POST /v1/eventos` recebe o envelope `{mensagem_id, tipo, versao, ocorrido_em, correlation_id, dados}` e responde `202` (inclusive para duplicata já recebida). Envelope inválido retorna `400`. A rota grava o evento no outbox e o publica no broker.
- [CA-NOT-01-02] Cada papel só publica seus tipos: `entregador` só `entrega.*`, `loja` só `pedido.*`; `admin` publica ambos.
- [CA-NOT-01-03] O consumidor usa inbox: mensagem com `mensagem_id` repetido é confirmada sem refazer o efeito.
- [CA-NOT-01-04] Se existe template para o `tipo`, o e-mail do destinatário é obtido em `GET /perfis/{id}` (Equipe 1, com cache de 5 minutos) e enviado via SMTP. Tipos sem template não geram e-mail.
- [CA-NOT-01-05] Em caso de falha, a mensagem segue as filas de retry com TTL crescente (`notificacoes.emails.retry.1` a `.5`) e, esgotadas as tentativas, vai para `notificacoes.dlq`. Falha ao buscar o perfil (Equipe 1 fora) também é reprocessada, sem perder a mensagem.
- [CA-NOT-01-06] O status de cada notificação é registrado (`pendente`, `enviada`, `falhou`).

#### [US-NOT-002] Receber webhooks por inscrição

Como sistema externo (de qualquer equipe), eu quero me inscrever para receber eventos por webhook, de forma que eu seja alertado sobre eventos do pedido. Rotas: `POST /v1/webhooks`, `GET /v1/webhooks`, `DELETE /v1/webhooks/{assinatura_id}` e `GET /v1/webhooks/{assinatura_id}/entregas`.

- [CA-NOT-02-01] A inscrição contém `url` e a lista de `eventos` (padrões como `pagamento.*`). A URL exige `https`, exceto em ambiente local (`422` se inválida). O `segredo` é exibido apenas na resposta `201` da criação.
- [CA-NOT-02-02] A entrega é um `POST` com o envelope e os cabeçalhos `X-Assinatura` (`sha256=<HMAC-SHA256(segredo, "<timestamp>.<corpo>")>`), `X-Assinatura-Timestamp`, `X-Evento-Id` e `X-Evento-Tipo`. Sucesso é qualquer `2xx` em até 5 segundos.
- [CA-NOT-02-03] Em caso de falha, a entrega é reenfileirada em `notificacoes.webhooks.retry.1` a `.5` (TTL de 1 s, 5 s, 30 s, 2 min e 10 min). Após a quinta falha, a entrega fica com status `falhou` e a mensagem vai para `notificacoes.dlq`.
- [CA-NOT-02-04] O histórico de tentativas fica em `GET /v1/webhooks/{assinatura_id}/entregas` (paginado; `404` se não existir, `403` se a inscrição for de outro usuário).
- [CA-NOT-02-05] `GET /v1/webhooks` lista as inscrições do próprio `sub`; `admin` vê todas. A remoção retorna `204`.

#### [US-NOT-003] Consultar notificações

Como um serviço consumidor, eu quero consultar as notificações geradas para um destinatário e o status de cada uma, de forma que eu possa confirmar se foram entregues.

- [CA-NOT-03-01] `GET /v1/notificacoes?destinatario_id=` lista as notificações de forma paginada; quem não é `admin` vê só as próprias.
- [CA-NOT-03-02] **Consulta por identificador:** `GET /v1/notificacoes/{id}` foi implementada no PR #69 (no contrato: `docs/openapi/notificacoes.json`, parâmetro `notificacao_id`). Se a notificação não existir, o sistema retorna `404` no formato padrão.

### 5.3. Avaliações

#### [US-AVA-001] Criar avaliação

Como cliente (via front-end de outra equipe), eu quero avaliar um pedido entregue, de forma que eu possa expressar minha opinião sobre a experiência. Rota: `POST /v1/avaliacoes`.

- [CA-AVA-01-01] A solicitação contém `pedido_id`, `nota_restaurante` (1 a 5), `nota_entrega` (1 a 5, opcional) e `comentario` (até 1000 caracteres, opcional). O cliente é identificado pelo `sub` do token, não pelo corpo.
- [CA-AVA-01-02] O sistema valida o token JWT localmente, com a chave pública (JWKS) da Identidade.
- [CA-AVA-01-03] O sistema consulta `GET /pedidos/{id}` (Equipe 3): o pedido deve estar entregue e pertencer ao cliente do token (`403` se for de outro cliente). O `restaurante_id` é copiado do pedido.
- [CA-AVA-01-04] Pedido não entregue retorna `422 PEDIDO_NAO_ENTREGUE`; segunda avaliação do mesmo pedido, `409 AVALIACAO_DUPLICADA`; Equipe 3 indisponível, `503`.
- [CA-AVA-01-05] Ao registrar, o serviço grava o evento `avaliacao.registrada` no outbox.

#### [US-AVA-002] Consultar avaliações

Como um serviço consumidor (ou usuário final), eu quero listar avaliações e ver o resumo de um restaurante. Rotas: `GET /v1/avaliacoes?restaurante_id=&pedido_id=` e `GET /v1/resumos-avaliacoes/{restaurante_id}`.

- [CA-AVA-02-01] A consulta de avaliações de um pedido é um filtro da listagem (`?pedido_id=`), paginada, e não uma rota separada.
- [CA-AVA-02-02] O resumo retorna `restaurante_id`, `media_restaurante`, `media_entrega` e `total`.

#### [US-AVA-003] Consultar avaliação específica

Como um serviço consumidor, eu quero consultar os detalhes de uma avaliação específica, de forma que eu possa exibir seu conteúdo completo. Rota: `GET /v1/avaliacoes/{avaliacao_id}`.

- [CA-AVA-03-01] Se a avaliação não existir, o sistema deve retornar `404` no formato padrão.

#### [US-AVA-004] Abrir e resolver disputa

Como cliente, eu quero abrir uma disputa sobre um pedido, de forma que eu possa contestar o que recebi e, se procedente, ser reembolsado. A disputa é um recurso próprio. Rotas: `POST /v1/disputas`, `GET /v1/disputas?status=`, `GET /v1/disputas/{disputa_id}` e `PATCH /v1/disputas/{disputa_id}`.

- [CA-AVA-04-01] A abertura contém `pedido_id`, `motivo` (`item_faltando`, `pedido_errado`, `nao_entregue` ou `qualidade`), `descricao` e `valor_solicitado_centavos`.
- [CA-AVA-04-02] Deve existir pagamento `aprovado` ou `parcialmente_estornado` do pedido (`422 PAGAMENTO_NAO_ENCONTRADO`), consultado em `GET /v1/pagamentos?pedido_id=`. Só uma disputa não-terminal por pedido (`409 DISPUTA_JA_ABERTA`). O valor solicitado não pode passar do saldo estornável do pagamento (`422 VALOR_EXCEDE_PAGO`).
- [CA-AVA-04-03] A decisão é do `admin`, por `PATCH` com `status` (`procedente` ou `improcedente`), `valor_aprovado_centavos` (opcional) e `parecer`. Não-admin recebe `403`; transição inválida, `409 TRANSICAO_INVALIDA`.
- [CA-AVA-04-04] Disputa procedente aciona a saga: status `estorno_pendente`, chamada a `POST /v1/pagamentos/{pagamento_id}/estornos` com `Idempotency-Key: disputa-{disputa_id}`. Sucesso leva a `resolvida` (`200`); falha transitória mantém `estorno_pendente` (`202`) e o worker repete até 10 vezes; falha definitiva leva a `estorno_falhou`.
- [CA-AVA-04-05] O serviço publica via outbox `disputa.aberta`, `disputa.resolvida` (procedente ou improcedente) e `disputa.estorno_falhou`.
- [CA-AVA-04-06] A listagem do `cliente` mostra só as suas disputas.

---

## 6. Requisitos Não Funcionais

### 6.1. [RNF-001] Segurança

Como consumidor dos serviços, eu quero que apenas usuários autenticados executem operações sensíveis, de forma que a integridade financeira e a privacidade dos dados sejam preservadas.

- [CA-SEG-01] Todas as rotas, exceto `/saude/*` e `/docs`, exigem `Authorization: Bearer <jwt>`. O token é validado localmente com a chave pública (JWKS) da Identidade, mantida em cache; se a Identidade estiver fora, vale a última chave conhecida.
- [CA-SEG-02] Dados sensíveis (número de cartão, CVV, titular, validade, token JWT e segredo de webhook) não aparecem em logs.
- [CA-SEG-03] A autorização considera o papel do token (`cliente`, `loja`, `entregador`, `admin`, `servico`). O papel `servico` só é aceito nas rotas que o declaram.

### 6.2. [RNF-002] Desempenho

- [CA-DES-01] Cada endpoint deve responder em até 2 segundos em condições normais de rede e carga.

### 6.3. [RNF-003] Confiabilidade e Resiliência

- [CA-CONF-01] Se uma dependência externa (Identidade, Checkout/Pedidos, ou entre os próprios serviços do grupo) estiver indisponível, o serviço não pode encerrar o processo: captura a falha e responde `503 DEPENDENCIA_INDISPONIVEL`.
- [CA-CONF-02] Falhas de envio de e-mail e de entrega de webhook são reprocessadas por filas de retry com TTL e, esgotadas as tentativas, vão para a DLQ (`notificacoes.dlq`).
- [CA-CONF-03] **Outbox:** todo serviço que publica eventos os grava na mesma transação da mudança de estado; um relay publica depois. Com o broker fora, as APIs continuam operando e o outbox acumula.
- [CA-CONF-04] **Inbox:** todo consumidor grava o `mensagem_id` na mesma transação do efeito; mensagem repetida é confirmada sem refazer o efeito.
- [CA-CONF-05] **Circuit breaker** por dependência (abre após 5 falhas consecutivas, meio-aberto após 30 s) e **retry** em GET e em POST com `Idempotency-Key`, nunca em 4xx.
- [CA-CONF-06] A prontidão (`GET /saude/pronto`) verifica banco e broker, não as outras equipes; `GET /saude/vivo` indica apenas que o processo está de pé.

### 6.4. [RNF-004] Padrões de dados e formato

- [CA-PAD-01] Toda resposta de erro segue o formato `{"erro": true, "mensagem": "...", "codigo": "PAGAMENTO_RECUSADO", "correlation_id": "..."}`, acompanhada do código HTTP correto. `erro` e `mensagem` são os campos obrigatórios do documento da disciplina; `codigo` e `correlation_id` são adicionais e não quebram consumidores. `500` nunca expõe stack trace.
- [CA-PAD-02] Toda data/hora trafegada deve seguir o padrão ISO 8601 em UTC (ex.: `2026-10-14T14:30:00Z`).
- [CA-PAD-03] Todo valor financeiro deve trafegar como número inteiro representando centavos, em campos `*_centavos` (nunca ponto flutuante).
- [CA-PAD-04] Rotas em português, substantivos no plural e prefixo `/v1`; ações são sub-recursos (`/estornos`) ou `PATCH` de status. JSON em `snake_case`.
- [CA-PAD-05] **Idempotência:** `Idempotency-Key` é obrigatório nos `POST` com efeito financeiro (`/v1/pagamentos` e `/v1/pagamentos/{pagamento_id}/estornos`).
- [CA-PAD-06] **Correlação:** `X-Correlation-ID` é propagado em toda chamada e todo evento, e gerado quando ausente; `traceparent` (W3C) também é propagado.

### 6.5. [RNF-005] Disponibilidade

- [CA-DISP-01] Os serviços devem poder ser inicializados de forma independente via `docker compose up -d --build`, sem exigir configuração manual adicional (os mocks sobem com `--profile mocks`).

### 6.6. [RNF-006] Hardware e Software

- [CA-HW-01] Cada serviço deve ser conteinerizado (Docker), com `Dockerfile` próprio; o `compose.yaml` raiz orquestra os três.
- [CA-HW-02] Cada serviço deve rodar em porta fixa e distinta: Pagamentos (8013), Notificações (8014), Avaliações (8015).
- [CA-HW-03] Cada serviço deve utilizar seu próprio banco de dados PostgreSQL, isolado dos demais.

### 6.7. [RNF-007] Cobertura de Testes

- [CA-TEST-01] Cada serviço deve manter cobertura mínima de 75% de testes automatizados (unitários, de integração e de API), garantida no CI.

---

## 7. Requisitos de Integração

Esta seção detalha os requisitos específicos de comunicação entre os serviços da plataforma, complementares aos requisitos funcionais e não funcionais.

### 7.1. [RI-001] Contrato de API documentado

Todos os endpoints HTTP expostos pelos 3 serviços estão documentados em OpenAPI (`docs/openapi/*.json`, também em `/docs` de cada serviço) e os eventos em AsyncAPI (`docs/asyncapi/*.json`). O CI verifica que os contratos gerados são iguais aos de `docs/`.

### 7.2. [RI-002] Validação de identidade centralizada

Pagamentos, Notificações e Avaliações não emitem tokens nem mantêm usuários: o token é emitido pela Identidade (Equipe 1). A validação é feita localmente com a chave pública obtida do JWKS da Identidade, com cache e TTL. Se a Identidade não expuser JWKS, um adapter alternativo usa o endpoint de validação dela (decisão pendente, issue #38). Chamadas feitas por workers, sem usuário na origem, usam o token de serviço interno da equipe.

### 7.3. [RI-003] Integração síncrona via HTTP e assíncrona via eventos

A integração síncrona com outros serviços (Equipes 1, 3 e 4 e entre Pagamentos, Notificações e Avaliações) é feita por HTTP/REST. Eventos são publicados no RabbitMQ (exchange `financeiro.eventos`, tipo topic) apenas entre os serviços da Equipe 5; as demais equipes publicam eventos por `POST /v1/eventos` e assinam webhooks, sem acessar o broker. Continuam proibidos a comunicação em memória e o acesso direto ao banco de outro serviço.

### 7.4. [RI-004] Timeout e tolerância a falhas

Toda chamada HTTP a um serviço externo (Identidade, Checkout/Pedidos, ou entre serviços do grupo) tem timeout de 1 s para conectar e 3 s para ler, com prazo total de 8 s por chamada lógica, retry e circuit breaker. Falhas (timeout, conexão recusada, `5xx`) são convertidas em `503 DEPENDENCIA_INDISPONIVEL`, nunca em uma exceção não tratada que derrube o processo.

### 7.5. [RI-005] Rastreabilidade de integração

Toda chamada HTTP de saída gera uma linha de log antes e outra depois (dependência, método, rota, status e duração), e todo evento publicado ou consumido gera uma linha com `tipo` e `mensagem_id`, informando se a inbox o considerou novo ou duplicado. Todas as linhas levam o `correlation_id`; os traces seguem para o Jaeger.

### 7.6. [RI-006] Isolamento de bancos de dados

Cada serviço mantém seu próprio banco de dados PostgreSQL, sem cruzamento de dados (JOINs) com o banco de outro serviço. Qualquer dado necessário de outro domínio deve ser obtido via chamada HTTP ao serviço dono daquele dado.

### 7.7. [RI-007] Orquestração local do grupo

O `compose.yaml` raiz do monorepo `delivery-financeiro` sobe os 3 serviços, seus workers, seus bancos, o RabbitMQ, o Mailpit e o Jaeger, e, com `--profile mocks`, os mocks das Equipes 1, 3 e 4. Os serviços se comunicam entre si pelo nome do container.

### 7.8. [RI-008] Alinhamento com as outras equipes (pendente)

Endereços, portas e detalhes de contrato com a Equipe 1 (JWKS, `GET /perfis/{id}`, credencial de serviço) dependem da issue #38; os com as Equipes 3 e 4 (`GET /pedidos/{id}`, chamada a `POST /v1/pagamentos`, publicação em `POST /v1/eventos`), da issue #39. Ambas estão abertas e os valores acima seguem a especificação (seção 12) até o alinhamento: **a alinhar**.

---

## 8. Casos de Uso

### [UC-PAG-001] Processar Pagamento

| Campo | Descrição |
|---|---|
| Ator principal | Serviço de Checkout (Equipe 3) |
| Ator secundário | Serviço de Identidade (JWKS), serviço de Pedidos (Equipe 3) |
| Pré-condições | O pedido existe, pertence ao cliente do token e está pronto para cobrança |
| Fluxo principal | 1. Checkout chama `POST /v1/pagamentos` com `pedido_id`, `metodo`, `Idempotency-Key` e o token JWT do usuário.<br>2. Pagamentos valida o token localmente (JWKS).<br>3. Pagamentos consulta o pedido (`GET /pedidos/{id}`) e obtém o valor.<br>4. Pagamentos aplica o antifraude e o gateway simulado, e registra o pagamento.<br>5. Pagamentos grava o evento no outbox e retorna `201` ao Checkout.<br>6. O relay publica `pagamento.aprovado`, que Notificações consome. |
| Fluxos de exceção | FE01 — Token inválido: `401` no formato padrão.<br>FE02 — Pedido ou gateway indisponível: `503 DEPENDENCIA_INDISPONIVEL`, sem derrubar o processo.<br>FE03 — Campos inválidos ou `Idempotency-Key` ausente: `400`/`422`.<br>FE04 — Pagamento recusado: `409 PAGAMENTO_RECUSADO`, com tentativa persistida.<br>FE05 — Pedido já pago: `409 PEDIDO_JA_PAGO`. |
| Pós-condições | O pagamento é registrado com status aprovado ou recusado; o evento correspondente fica no outbox. |
| Regras de negócio | RN01: valor sempre em centavos (inteiro), lido do pedido. RN02: token validado antes de qualquer escrita. RN03: um pagamento aprovado por pedido. |
| Rastreamento | [US-PAG-001] |

### [UC-NOT-001] Enviar Notificação a partir de Evento

| Campo | Descrição |
|---|---|
| Ator principal | Serviço publicador do evento (Pagamentos, Avaliações, Checkout ou Logística) |
| Ator secundário | Serviço de Identidade (Equipe 1) |
| Pré-condições | Um evento que exige notificação ocorreu (ex.: pagamento aprovado) |
| Fluxo principal | 1. O evento chega pelo broker ou por `POST /v1/eventos`.<br>2. Notificações verifica a inbox; se o `mensagem_id` é novo, registra a notificação com status "pendente".<br>3. Notificações busca o e-mail do destinatário em `GET /perfis/{id}` e envia o e-mail.<br>4. Notificações atualiza o status para "enviada" e, para cada inscrição de webhook que casa com o tipo, enfileira a entrega. |
| Fluxos de exceção | FE01 — Falha no envio: a mensagem segue as filas de retry com TTL; após esgotar, vai para a DLQ e o status é "falhou", sem interromper quem publicou.<br>FE02 — Evento duplicado: confirmado sem refazer o efeito. |
| Pós-condições | A notificação é registrada com seu status final. |
| Rastreamento | [US-NOT-001], [US-NOT-002] |

### [UC-AVA-001] Avaliar Pedido Entregue

| Campo | Descrição |
|---|---|
| Ator principal | Cliente (via front-end de outra equipe) |
| Ator secundário | Serviço de Identidade, serviço de Checkout/Pedidos |
| Pré-condições | O cliente está autenticado e o pedido foi marcado como entregue |
| Fluxo principal | 1. O cliente chama `POST /v1/avaliacoes` com `pedido_id`, `nota_restaurante`, `nota_entrega` e `comentario`.<br>2. Avaliações valida o token localmente (JWKS).<br>3. Avaliações consulta `GET /pedidos/{id}` e confirma que o pedido é do cliente e foi entregue.<br>4. Avaliações registra a avaliação e publica `avaliacao.registrada` via outbox. |
| Fluxos de exceção | FE01 — Pedido não entregue: `422 PEDIDO_NAO_ENTREGUE`.<br>FE02 — Pedido de outro cliente: `403`.<br>FE03 — Avaliação duplicada: `409 AVALIACAO_DUPLICADA`.<br>FE04 — Checkout indisponível: `503` amigável. |
| Pós-condições | A avaliação é registrada e associada ao pedido e ao cliente. |
| Rastreamento | [US-AVA-001] |

### [UC-AVA-002] Resolver Disputa com Estorno

| Campo | Descrição |
|---|---|
| Ator principal | Administrador |
| Ator secundário | Serviço de Pagamentos |
| Pré-condições | Existe disputa aberta sobre um pedido com pagamento aprovado ou parcialmente estornado |
| Fluxo principal | 1. O admin chama `PATCH /v1/disputas/{disputa_id}` com `status = procedente`.<br>2. Avaliações marca `estorno_pendente`.<br>3. Avaliações chama `POST /v1/pagamentos/{pagamento_id}/estornos` com `Idempotency-Key: disputa-{disputa_id}`.<br>4. Em caso de sucesso, a disputa vai para `resolvida` e `disputa.resolvida` é publicado. |
| Fluxos de exceção | FE01 — Pagamentos indisponível: resposta `202`, disputa permanece `estorno_pendente` e o worker repete até 10 vezes.<br>FE02 — Recusa definitiva ou tentativas esgotadas: `estorno_falhou` e evento `disputa.estorno_falhou`.<br>FE03 — Não-admin: `403`. |
| Pós-condições | A disputa termina em `resolvida`, `improcedente` ou `estorno_falhou`. |
| Rastreamento | [US-AVA-004], [US-PAG-003] |

---

## 9. Gerência de Requisitos

### Requisitos Funcionais

| ID | Descrição | Prioridade | Dependências |
|---|---|---|---|
| US-PAG-001 | Processar pagamento | Alta | Identidade (Eq. 1), Pedidos (Eq. 3) |
| US-PAG-002 | Consultar pagamento | Alta | US-PAG-001 |
| US-PAG-003 | Estornar pagamento | Média | US-PAG-001 |
| US-NOT-001 | Enviar e-mail a partir de eventos | Alta | Identidade (Eq. 1) |
| US-NOT-002 | Receber webhooks por inscrição | Média | NDA |
| US-NOT-003 | Consultar notificações | Média | US-NOT-001 |
| US-AVA-001 | Criar avaliação | Alta | Identidade (Eq. 1), Pedidos (Eq. 3) |
| US-AVA-002 | Consultar avaliações e resumo | Alta | US-AVA-001 |
| US-AVA-003 | Consultar avaliação específica | Média | US-AVA-001 |
| US-AVA-004 | Abrir e resolver disputa | Média | US-AVA-001, US-PAG-003 |

### Requisitos Não Funcionais

| ID | Descrição | Prioridade | Dependências |
|---|---|---|---|
| RNF-001 | Segurança (JWT validado via JWKS) | Alta | Identidade (Eq. 1) |
| RNF-002 | Desempenho (resposta ≤ 2s) | Alta | NDA |
| RNF-003 | Confiabilidade e resiliência (outbox, inbox, retry, DLQ) | Alta | NDA |
| RNF-004 | Padrões de dados e formato (erro, idempotência, correlação) | Alta | NDA |
| RNF-005 | Disponibilidade | Média | NDA |
| RNF-006 | Hardware e software (Docker, portas, bancos isolados) | Alta | NDA |
| RNF-007 | Cobertura de testes ≥ 75% | Alta | NDA |

### Requisitos de Integração

| ID | Descrição | Prioridade | Dependências |
|---|---|---|---|
| RI-001 | Contrato de API documentado (OpenAPI e AsyncAPI) | Alta | NDA |
| RI-002 | Validação de identidade centralizada (JWKS) | Alta | Identidade (Eq. 1) |
| RI-003 | Integração síncrona via HTTP e assíncrona via eventos | Alta | NDA |
| RI-004 | Timeout e tolerância a falhas | Alta | RNF-003 |
| RI-005 | Rastreabilidade de integração (logs e traces) | Média | NDA |
| RI-006 | Isolamento de bancos de dados | Alta | NDA |
| RI-007 | Orquestração local do grupo via compose | Média | RNF-006 |
| RI-008 | Alinhamento com as outras equipes (a alinhar) | Alta | Issues #38 e #39 |

---

## 10. Rastreabilidade: história, rota e PR

Os PRs abaixo são os que implementaram (ou corrigiram) cada serviço, conforme `git log` e a lista de PRs mesclados do repositório. As rotas conferem com `docs/openapi/*.json`, exceto onde indicado.

| História | Rota(s) | PR |
|---|---|---|
| US-PAG-001 | `POST /v1/pagamentos` | #22 (implementação); #25 (correções da revisão) |
| US-PAG-002 | `GET /v1/pagamentos/{pagamento_id}`, `GET /v1/pagamentos` | #22; #25 |
| US-PAG-003 | `POST /v1/pagamentos/{pagamento_id}/estornos`, `GET /v1/pagamentos/{pagamento_id}/estornos` | #22; #25 |
| US-NOT-001 | `POST /v1/eventos` (e consumo de eventos do broker) | #23 (implementação); #26 (correções da revisão); #63 (recusa de surrogate solto no envelope) |
| US-NOT-002 | `POST /v1/webhooks`, `GET /v1/webhooks`, `DELETE /v1/webhooks/{assinatura_id}`, `GET /v1/webhooks/{assinatura_id}/entregas` | #23; #26 |
| US-NOT-003 | `GET /v1/notificacoes` | #23; #26 |
| US-NOT-003 | `GET /v1/notificacoes/{id}` | #69 |
| US-AVA-001 | `POST /v1/avaliacoes` | #21 |
| US-AVA-002 | `GET /v1/avaliacoes`, `GET /v1/resumos-avaliacoes/{restaurante_id}` | #21 |
| US-AVA-003 | `GET /v1/avaliacoes/{avaliacao_id}` | #21 |
| US-AVA-004 | `POST /v1/disputas`, `GET /v1/disputas`, `GET /v1/disputas/{disputa_id}`, `PATCH /v1/disputas/{disputa_id}` | #21 (disputas e saga); #55 (teto da disputa passa a ser o saldo estornável) |

Complementos que afetam várias histórias: especificação de design (#19), fundação do monorepo e `libs/plataforma` (#20), correção de erros 500 em paginação e envelope de evento (#61), coleção Postman do fluxo completo (#56) e job E2E no CI (#59).

**A confirmar:** a atribuição de cada rota a um PR específico foi feita a partir dos títulos dos PRs e do histórico; ela deve ser conferida contra o diff de cada PR antes da entrega final.
