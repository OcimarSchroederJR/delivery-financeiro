# Levantamento de Requisitos — Financeiro e Pós

**Projeto:** Plataforma de Delivery — Integração de Sistemas
**Grupo:** Equipe 3 (Financeiro e Pós) — Sessão 3
**Versão:** 01.00
**Data:** 22/09/2026
**Identificador do documento:** LR-FIN
**Localização:** `delivery-financeiro/docs/levantamento-requisitos.md`

## Histórico de revisões

| Versão | Data | Autores | Descrição |
|---|---|---|---|
| 01.00 | 22/09/2026 | Luiz Tenório, João Gabriel, Alana Brito | Versão inicial do levantamento de requisitos dos serviços de Pagamentos, Notificações e Avaliações |

## Equipe

| Nome |
|---|
| Luiz Tenório |
| João Gabriel |
| Alana Brito |

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

---

## 1. Introdução

### 1.1. Propósito

Este documento especifica os requisitos dos serviços de **Pagamentos**, **Notificações** e **Avaliações**, sob responsabilidade da Equipe 3 (Financeiro e Pós) na disciplina de Integração de Sistemas. Ele serve como referência para o desenvolvimento, testes e integração desses serviços com os demais 12 microsserviços da Plataforma de Delivery.

### 1.2. Público-alvo

Este documento é destinado aos integrantes da equipe responsável pelos serviços aqui descritos, às demais equipes da disciplina que consomem ou são consumidas por esses serviços (Identidade, Checkout), e ao professor responsável pela avaliação do projeto.

### 1.3. Escopo

Este documento trata exclusivamente dos 3 serviços sob responsabilidade da Equipe 3:

- **Pagamentos** (porta 8051): processamento de transações financeiras de pedidos.
- **Notificações** (porta 8052): envio de e-mails e disparo de webhooks de alerta.
- **Avaliações** (porta 8053): coleta de notas, comentários e gestão de disputas.

Não fazem parte do escopo deste documento os requisitos dos demais 12 serviços da plataforma (Identidade, Catálogo, Checkout, Logística), que são de responsabilidade de outras equipes e documentados separadamente por elas.

### 1.4. Definições e Abreviações

| Termo | Definição |
|---|---|
| JWT | JSON Web Token, usado para autenticação entre serviços |
| RN | Regra de Negócio |
| CA | Critério de Aceite |
| US | User Story |
| RF | Requisito Funcional |
| RNF | Requisito Não Funcional |
| RI | Requisito de Integração |

### 1.5. Referências

- Documento de arquitetura de integração da disciplina: *Plataforma de Delivery — Arquitetura de Integração (15 Serviços)*.

### 1.6. Visão geral do documento

- Na seção 2 é apresentada uma visão geral dos serviços, seu contexto dentro da plataforma e seus consumidores.
- A seção 3 define as fronteiras de cada serviço: o que entra, o que sai, de quem e para quem.
- A seção 4 especifica as premissas e restrições do projeto.
- A seção 5 enumera os requisitos funcionais.
- A seção 6 enumera os requisitos não funcionais.
- A seção 7 detalha os requisitos de integração entre serviços.
- A seção 8 apresenta os principais casos de uso.
- A seção 9 traz a matriz de gerência e rastreamento dos requisitos.

---

## 2. Visão Geral do Produto

### 2.1. Contexto

A Plataforma de Delivery é composta por 15 microsserviços independentes, divididos entre 5 equipes, sem banco de dados compartilhado e sem comunicação em memória — toda integração ocorre via HTTP. A Equipe 3 (Financeiro e Pós) é responsável pela etapa de **fechamento do ciclo do pedido**: cobrar o cliente, avisá-lo sobre o andamento e coletar sua avaliação após a entrega.

### 2.2. Escopo do grupo Financeiro e Pós

| Serviço | Responsabilidade |
|---|---|
| Pagamentos | Processar, consultar e estornar transações financeiras de pedidos |
| Notificações | Enviar e-mails de confirmação e disparar webhooks de alerta |
| Avaliações | Coletar notas e comentários de pedidos entregues, e gerenciar disputas sobre avaliações |

### 2.3. Descrição dos consumidores (atores)

Diferente de um sistema com usuários finais diretos, os "usuários" destes serviços são majoritariamente **outros microsserviços da plataforma**:

- **Equipe 3 — Checkout** (`http://localhost:8031`): aciona Pagamentos ao concluir um pedido, e Notificações/Avaliações conforme o andamento do ciclo.
- **Equipe 1 — Identidade** (`http://localhost:8011`): validação de token JWT e consulta de dados de usuário, consumida por todos os 3 serviços.
- **Usuário final** (indireto): a pessoa que fez o pedido é impactada pelos efeitos destes serviços (cobrança, e-mail recebido, possibilidade de avaliar), mas nunca acessa estes serviços diretamente — sempre por meio do Checkout ou de um front-end mantido por outra equipe.
- **Administrador/Professor**: valida o funcionamento via Postman/Insomnia e observa os logs de integração no terminal.

---

## 3. Fronteiras dos Serviços

Esta seção define explicitamente o que **entra** e o que **sai** de cada serviço, delimitando sua responsabilidade dentro da integração.

### 3.1. Pagamentos

| Direção | Dado / Evento | De quem → Para quem | Protocolo |
|---|---|---|---|
| Entrada | Solicitação de processamento de pagamento (`pedido_id`, `metodo_pagamento`, `valor` em centavos) | Checkout (Eq. 3) → Pagamentos | HTTP/REST (JSON) |
| Entrada | Token JWT do usuário (para validação) | Checkout → Pagamentos → Identidade (Eq. 1) | HTTP/REST (Bearer token) |
| Entrada | Solicitação de consulta de status de transação | Checkout / Financeiro → Pagamentos | HTTP/REST |
| Entrada | Solicitação de estorno de transação aprovada | Checkout → Pagamentos | HTTP/REST |
| Saída | Confirmação/rejeição do pagamento (status da transação) | Pagamentos → Checkout | HTTP/REST (resposta síncrona) |
| Saída | Disparo de notificação de pagamento aprovado | Pagamentos → Notificações | HTTP/REST (chamada interna) |
| **Fora do escopo** | Cálculo de subtotal, aplicação de cupons, orquestração do pedido | — (é responsabilidade do Checkout) | — |
| **Fora do escopo** | Emissão de nota fiscal, integração com gateways de pagamento reais | — (fora do escopo da disciplina) | — |

### 3.2. Notificações

| Direção | Dado / Evento | De quem → Para quem | Protocolo |
|---|---|---|---|
| Entrada | Solicitação de envio de e-mail (`destinatario`, `assunto`, `mensagem`) | Pagamentos / Checkout → Notificações | HTTP/REST |
| Entrada | Solicitação de disparo de webhook (`url`, `payload`) | Checkout → Notificações | HTTP/REST |
| Entrada | Consulta de e-mail do usuário | Notificações → Identidade (Eq. 1) | HTTP/REST |
| Saída | Confirmação do envio ou falha (com retry) | Notificações → serviço solicitante | HTTP/REST (resposta síncrona) |
| Saída | E-mail efetivamente enviado | Notificações → caixa de e-mail do usuário final | SMTP (ou simulação em log, conforme decisão de implementação) |
| **Fora do escopo** | Definição do conteúdo de negócio da notificação (ex.: regras de quando notificar) | — (é decidido por quem aciona: Pagamentos ou Checkout) | — |

### 3.3. Avaliações

| Direção | Dado / Evento | De quem → Para quem | Protocolo |
|---|---|---|---|
| Entrada | Criação de avaliação (`pedido_id`, `usuario_id`, `nota`, `comentário`) | Usuário final (via front-end de outra equipe) → Avaliações | HTTP/REST |
| Entrada | Token JWT do usuário (para autenticação) | Avaliações → Identidade (Eq. 1) | HTTP/REST |
| Entrada | Confirmação de que o pedido existe e foi entregue | Avaliações → Checkout/Pedidos (Eq. 3) | HTTP/REST |
| Entrada | Abertura de disputa sobre uma avaliação | Usuário final → Avaliações | HTTP/REST |
| Saída | Notas e comentários de um pedido | Avaliações → quem consultar (Checkout, front-end) | HTTP/REST |
| **Fora do escopo** | Moderação de conteúdo ofensivo, cálculo de reputação agregada do restaurante | — (não especificado no escopo atual da disciplina) | — |

---

## 4. Premissas e Restrições

- Pressupõe-se que os 3 integrantes da equipe (Luiz Tenório, João Gabriel, Alana Brito) tenham disponibilidade para desenvolver, testar e integrar um serviço cada, seguindo o cronograma de ondas definido pela disciplina (Onda 3 — Financeiro só é ativado após um pedido ser gerado com sucesso pela Equipe 3 — Checkout).
- Pressupõe-se conhecimento em Node.js/TypeScript (NestJS), Git, GitHub, Docker e PostgreSQL.
- Cada serviço deve poder ser executado de forma isolada, sem depender da disponibilidade simultânea dos demais serviços da plataforma para subir (mas suas funcionalidades de integração dependerão deles em tempo de execução).
- O banco de dados de cada serviço é isolado; é proibido acesso direto (JOIN) ao banco de outro serviço, mesmo dentro do próprio grupo Financeiro e Pós.
- A comunicação entre Pagamentos, Notificações e Avaliações (e com os demais serviços da plataforma) ocorre exclusivamente via HTTP.

---

## 5. Requisitos Funcionais

*Como um <serviço/ator>, eu quero <função>, de forma que <razão/benefício>.*

### 5.1. Pagamentos

#### [US-PAG-001] Processar pagamento

Como o serviço de Checkout, eu quero solicitar o processamento do pagamento de um pedido, de forma que o cliente possa concluir a compra.

- [CA-PAG-01-01] A solicitação deve conter `pedido_id`, `metodo_pagamento` e `valor` (em centavos, inteiro) obrigatoriamente.
- [CA-PAG-01-02] O sistema deve validar o token JWT do usuário junto ao serviço de Identidade antes de processar.
- [CA-PAG-01-03] Ao concluir o processamento, o sistema deve retornar o status da transação (aprovado/recusado) e um identificador único da transação.
- [CA-PAG-01-04] Após aprovar o pagamento, o sistema deve acionar o serviço de Notificações para envio de confirmação.
- [CA-PAG-01-05] Se algum campo obrigatório estiver ausente, o sistema deve rejeitar a requisição com erro 400 no formato padrão.

#### [US-PAG-002] Consultar status de transação

Como o serviço de Checkout (ou outro consumidor autorizado), eu quero consultar o status de uma transação, de forma que eu possa saber se o pagamento de um pedido foi concluído.

- [CA-PAG-02-01] A consulta é feita pelo identificador da transação.
- [CA-PAG-02-02] Se a transação não existir, o sistema deve retornar erro 404 no formato padrão.

#### [US-PAG-003] Estornar pagamento

Como o serviço de Checkout, eu quero estornar uma transação previamente aprovada, de forma que o cliente seja reembolsado em caso de cancelamento do pedido.

- [CA-PAG-03-01] Apenas transações com status "aprovado" podem ser estornadas.
- [CA-PAG-03-02] Ao concluir o estorno, o sistema deve atualizar o status da transação para "estornado".
- [CA-PAG-03-03] Tentativas de estornar uma transação já estornada ou recusada devem retornar erro 400/409 no formato padrão.

### 5.2. Notificações

#### [US-NOT-001] Enviar e-mail

Como o serviço de Pagamentos ou Checkout, eu quero solicitar o envio de um e-mail de confirmação, de forma que o cliente seja informado sobre o andamento do seu pedido.

- [CA-NOT-01-01] A solicitação deve conter `destinatario`, `assunto` e `mensagem`.
- [CA-NOT-01-02] Em caso de falha no envio, o sistema deve realizar no mínimo 2 tentativas (retry) antes de reportar falha definitiva.
- [CA-NOT-01-03] O sistema deve registrar o status de cada notificação enviada (pendente, enviada, falha).

#### [US-NOT-002] Disparar webhook

Como o serviço de Checkout, eu quero disparar um webhook para uma URL cadastrada, de forma que sistemas externos sejam alertados sobre eventos do pedido.

- [CA-NOT-02-01] A solicitação deve conter `url` de destino e `payload` a ser enviado.
- [CA-NOT-02-02] Em caso de falha na entrega, o sistema deve aplicar a mesma política de retry (mínimo 2 tentativas).

#### [US-NOT-003] Consultar status de notificação

Como um serviço consumidor, eu quero consultar o status de uma notificação enviada, de forma que eu possa confirmar se ela foi entregue.

- [CA-NOT-03-01] A consulta é feita pelo identificador da notificação.
- [CA-NOT-03-02] Se a notificação não existir, o sistema deve retornar erro 404 no formato padrão.

### 5.3. Avaliações

#### [US-AVA-001] Criar avaliação

Como o usuário final (via front-end de outra equipe), eu quero avaliar um pedido entregue, de forma que eu possa expressar minha opinião sobre a experiência.

- [CA-AVA-01-01] A solicitação deve conter `pedido_id`, `usuario_id`, `nota` (1 a 5) e `comentário`.
- [CA-AVA-01-02] O sistema deve validar o token JWT do usuário junto à Identidade.
- [CA-AVA-01-03] O sistema deve confirmar junto ao serviço de Checkout/Pedidos que o pedido existe e foi entregue antes de aceitar a avaliação.
- [CA-AVA-01-04] Se o pedido não existir ou não estiver entregue, o sistema deve rejeitar a avaliação com erro 400/403 no formato padrão.

#### [US-AVA-002] Consultar avaliações de um pedido

Como um serviço consumidor (ou usuário final), eu quero consultar as avaliações de um pedido, de forma que eu possa visualizar o feedback registrado.

- [CA-AVA-02-01] A consulta retorna todas as avaliações associadas ao `pedido_id`.

> **Nota de implementação:** a rota de consulta por pedido (`GET /avaliacoes/pedido/{pedido_id}`) deve ter um path distinto da rota de consulta de avaliação individual (`GET /avaliacoes/{id}`), para evitar colisão de rotas — ver [README do serviço de Avaliações](../services/avaliacoes/README.md).

#### [US-AVA-003] Consultar avaliação específica

Como um serviço consumidor, eu quero consultar os detalhes de uma avaliação específica, de forma que eu possa exibir seu conteúdo completo.

- [CA-AVA-03-01] Se a avaliação não existir, o sistema deve retornar erro 404 no formato padrão.

#### [US-AVA-004] Abrir disputa

Como o usuário final, eu quero abrir uma disputa sobre uma avaliação, de forma que eu possa contestar uma nota ou comentário que considero injusto.

- [CA-AVA-04-01] A disputa deve estar associada a uma avaliação existente.
- [CA-AVA-04-02] O sistema deve registrar a disputa com informações de rastreabilidade (data/hora, autor).

---

## 6. Requisitos Não Funcionais

### 6.1. [RNF-001] Segurança

Como consumidor dos serviços, eu quero que apenas usuários autenticados executem operações sensíveis, de forma que a integridade financeira e a privacidade dos dados sejam preservadas.

- [CA-SEG-01] Toda operação de escrita (criar pagamento, estornar, criar avaliação, abrir disputa) deve validar o token JWT junto ao serviço de Identidade.
- [CA-SEG-02] Dados sensíveis (valores, métodos de pagamento) não devem ser expostos em logs.

### 6.2. [RNF-002] Desempenho

- [CA-DES-01] Cada endpoint deve responder em até 2 segundos em condições normais de rede e carga.

### 6.3. [RNF-003] Confiabilidade e Resiliência

- [CA-CONF-01] Se uma dependência externa (Identidade, Checkout, ou entre os próprios serviços do grupo) estiver indisponível, o serviço não pode encerrar o processo — deve capturar a falha e retornar um erro amigável ao chamador.
- [CA-CONF-02] Falhas de envio de notificação devem ser reprocessadas automaticamente (mínimo 2 tentativas) antes de serem reportadas como falha definitiva.

### 6.4. [RNF-004] Padrões de dados e formato

- [CA-PAD-01] Toda resposta de erro deve seguir o formato `{"erro": true, "mensagem": "Detalhes da falha"}`, acompanhada do código HTTP correto.
- [CA-PAD-02] Toda data/hora trafegada deve seguir o padrão ISO 8601 (ex.: `2026-08-24T14:30:00Z`).
- [CA-PAD-03] Todo valor financeiro deve trafegar como número inteiro representando centavos (nunca ponto flutuante).

### 6.5. [RNF-005] Disponibilidade

- [CA-DISP-01] Os serviços devem poder ser inicializados de forma independente via `docker compose up`, sem exigir configuração manual adicional.

### 6.6. [RNF-006] Hardware e Software

- [CA-HW-01] Cada serviço deve ser conteinerizado (Docker), com `Dockerfile` e `docker-compose.yml` próprios.
- [CA-HW-02] Cada serviço deve rodar em porta fixa e distinta: Pagamentos (8051), Notificações (8052), Avaliações (8053).
- [CA-HW-03] Cada serviço deve utilizar seu próprio banco de dados PostgreSQL, isolado dos demais.

### 6.7. [RNF-007] Cobertura de Testes

- [CA-TEST-01] Cada serviço deve manter cobertura mínima de 75% de testes automatizados (unitários e de integração).

---

## 7. Requisitos de Integração

Esta seção detalha os requisitos específicos de comunicação entre os serviços da plataforma, complementares aos requisitos funcionais e não funcionais.

### 7.1. [RI-001] Contrato de API documentado

Todos os endpoints expostos pelos 3 serviços devem estar documentados via Swagger/OpenAPI, disponível em `/docs` de cada serviço, permitindo que outras equipes consumam mocks antes da implementação real estar pronta.

### 7.2. [RI-002] Validação de identidade centralizada

Pagamentos, Notificações e Avaliações não devem implementar lógica própria de autenticação — toda validação de token JWT deve ser delegada ao serviço de Identidade (`http://localhost:8011`), evitando duplicação de regras de autenticação entre equipes.

### 7.3. [RI-003] Comunicação exclusivamente via HTTP

Não é permitida comunicação em memória, filas compartilhadas ou acesso direto a banco de dados de outro serviço (mesmo dentro do próprio grupo). Toda troca de dados entre Pagamentos, Notificações, Avaliações e os demais serviços da plataforma deve ocorrer por chamadas HTTP/REST síncronas.

### 7.4. [RI-004] Timeout e tolerância a falhas

Toda chamada HTTP a um serviço externo (Identidade, Checkout, ou entre serviços do próprio grupo) deve ter um timeout configurado, e sua falha (timeout, conexão recusada, erro 5xx) deve ser tratada e convertida em uma resposta de erro amigável ao chamador original, nunca em uma exceção não tratada que derrube o processo.

### 7.5. [RI-005] Rastreabilidade de integração

Cada chamada recebida de ou enviada para outro serviço deve ser registrada em log no console, permitindo a verificação visual (pelo professor ou pela equipe) de que a integração de fato ocorreu — por exemplo, o serviço de Pagamentos imprimindo no console que está acionando o serviço de Notificações.

### 7.6. [RI-006] Isolamento de bancos de dados

Cada serviço mantém seu próprio banco de dados PostgreSQL, sem cruzamento de dados (JOINs) com o banco de outro serviço. Qualquer dado necessário de outro domínio deve ser obtido via chamada HTTP ao serviço dono daquele dado.

### 7.7. [RI-007] Orquestração local do grupo

O `docker-compose.yml` raiz do monorepo `delivery-financeiro` deve subir os 3 serviços do grupo e seus respectivos bancos de dados em uma rede Docker compartilhada, permitindo que Pagamentos, Notificações e Avaliações se comuniquem entre si pelo nome do container, sem expor essa comunicação interna à rede externa desnecessariamente.

---

## 8. Casos de Uso

### [UC-PAG-001] Processar Pagamento

| Campo | Descrição |
|---|---|
| Ator principal | Serviço de Checkout |
| Ator secundário | Serviço de Identidade, Serviço de Notificações |
| Pré-condições | O pedido foi validado pelo Checkout e está pronto para cobrança |
| Fluxo principal | 1. Checkout envia `pedido_id`, `metodo_pagamento` e `valor` (centavos) com token JWT do usuário.<br>2. Pagamentos valida o token junto à Identidade.<br>3. Pagamentos registra a transação e define o status.<br>4. Pagamentos aciona Notificações para envio de confirmação.<br>5. Pagamentos retorna o status da transação ao Checkout. |
| Fluxos de exceção | FE01 — Token inválido: retorna erro 401 no formato padrão.<br>FE02 — Identidade indisponível: retorna erro 503 amigável, sem derrubar o processo.<br>FE03 — Campos obrigatórios ausentes: retorna erro 400. |
| Pós-condições | A transação é registrada com status aprovado ou recusado; uma notificação é disparada em caso de aprovação. |
| Regras de negócio | RN01: valor sempre em centavos (inteiro). RN02: token deve ser validado antes de qualquer escrita. |
| Rastreamento | [US-PAG-001] |

### [UC-NOT-001] Enviar Notificação de Confirmação

| Campo | Descrição |
|---|---|
| Ator principal | Serviço de Pagamentos (ou Checkout) |
| Ator secundário | Serviço de Identidade |
| Pré-condições | Um evento que exige notificação ocorreu (ex.: pagamento aprovado) |
| Fluxo principal | 1. Serviço solicitante envia `destinatario`, `assunto` e `mensagem`.<br>2. Notificações registra a solicitação com status "pendente".<br>3. Notificações tenta o envio.<br>4. Notificações atualiza o status para "enviada" ou tenta novamente em caso de falha (mínimo 2 tentativas). |
| Fluxos de exceção | FE01 — Falha após todas as tentativas: status é marcado como "falha", sem interromper o serviço solicitante. |
| Pós-condições | A notificação é registrada com seu status final. |
| Rastreamento | [US-NOT-001] |

### [UC-AVA-001] Avaliar Pedido Entregue

| Campo | Descrição |
|---|---|
| Ator principal | Usuário final (via front-end de outra equipe) |
| Ator secundário | Serviço de Identidade, Serviço de Checkout/Pedidos |
| Pré-condições | O usuário está autenticado e o pedido foi marcado como entregue |
| Fluxo principal | 1. Usuário envia `pedido_id`, `usuario_id`, `nota` e `comentário`.<br>2. Avaliações valida o token junto à Identidade.<br>3. Avaliações confirma junto ao Checkout que o pedido existe e foi entregue.<br>4. Avaliações registra a avaliação. |
| Fluxos de exceção | FE01 — Pedido não entregue: retorna erro 403 no formato padrão.<br>FE02 — Checkout indisponível: retorna erro 503 amigável. |
| Pós-condições | A avaliação é registrada e associada ao pedido e ao usuário. |
| Rastreamento | [US-AVA-001] |

---

## 9. Gerência de Requisitos

### Requisitos Funcionais

| ID | Descrição | Prioridade | Dependências |
|---|---|---|---|
| US-PAG-001 | Processar pagamento | Alta | Identidade (Eq. 1), Notificações |
| US-PAG-002 | Consultar status de transação | Alta | US-PAG-001 |
| US-PAG-003 | Estornar pagamento | Média | US-PAG-001 |
| US-NOT-001 | Enviar e-mail | Alta | Identidade (Eq. 1) |
| US-NOT-002 | Disparar webhook | Média | NDA |
| US-NOT-003 | Consultar status de notificação | Média | US-NOT-001, US-NOT-002 |
| US-AVA-001 | Criar avaliação | Alta | Identidade (Eq. 1), Checkout (Eq. 3) |
| US-AVA-002 | Consultar avaliações de um pedido | Alta | US-AVA-001 |
| US-AVA-003 | Consultar avaliação específica | Média | US-AVA-001 |
| US-AVA-004 | Abrir disputa | Média | US-AVA-001 |

### Requisitos Não Funcionais

| ID | Descrição | Prioridade | Dependências |
|---|---|---|---|
| RNF-001 | Segurança (validação JWT) | Alta | Identidade (Eq. 1) |
| RNF-002 | Desempenho (resposta ≤ 2s) | Alta | NDA |
| RNF-003 | Confiabilidade e resiliência | Alta | NDA |
| RNF-004 | Padrões de dados e formato | Alta | NDA |
| RNF-005 | Disponibilidade | Média | NDA |
| RNF-006 | Hardware e software (Docker, portas, bancos isolados) | Alta | NDA |
| RNF-007 | Cobertura de testes ≥ 75% | Alta | NDA |

### Requisitos de Integração

| ID | Descrição | Prioridade | Dependências |
|---|---|---|---|
| RI-001 | Contrato de API documentado (Swagger) | Alta | NDA |
| RI-002 | Validação de identidade centralizada | Alta | Identidade (Eq. 1) |
| RI-003 | Comunicação exclusivamente via HTTP | Alta | NDA |
| RI-004 | Timeout e tolerância a falhas | Alta | RNF-003 |
| RI-005 | Rastreabilidade de integração (logs) | Média | NDA |
| RI-006 | Isolamento de bancos de dados | Alta | NDA |
| RI-007 | Orquestração local do grupo via docker-compose | Média | RNF-006 |
