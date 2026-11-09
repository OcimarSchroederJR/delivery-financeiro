# Roteiro da demonstração

Passo a passo para apresentar a Equipe 5 (Financeiro e Pós) do zero, mesmo para quem nunca rodou o
projeto. A ideia é mostrar, nos logs do terminal, um único `correlation_id` atravessando os três
serviços, e provar que o sistema não perde mensagens quando um worker cai.

## 1. Antes de começar

Você precisa de Docker, Postman (ou Node.js, para o Newman) e um navegador.

```bash
git clone <url do repositório> && cd delivery-financeiro
docker compose --profile mocks up -d --build
docker compose ps
```

Espere até `pagamentos`, `notificacoes`, `avaliacoes`, `rabbitmq`, `mailpit` e os três mocks
aparecerem como `healthy` (os containers `migrate-*` terminam sozinhos, com status `Exited (0)`).

Abra no navegador, cada um numa aba:

| O quê | URL |
|---|---|
| Painel do RabbitMQ (guest/guest), aba **Queues and Streams** | http://localhost:15672 |
| Mailpit (caixa de e-mails) | http://localhost:8025 |
| Jaeger (traces) | http://localhost:16686 |
| Swagger de Pagamentos, Notificações e Avaliações | http://localhost:8013/docs, http://localhost:8014/docs, http://localhost:8015/docs |

Importe no Postman a coleção `docs/postman/delivery-financeiro.postman_collection.json` e o ambiente
`docs/postman/local.postman_environment.json`, e selecione o ambiente **local**.

## 2. Terminais que ficam abertos

Use três terminais lado a lado, na pasta do projeto. Os logs saem em texto legível (formato
`console`); cada linha traz `servico`, `correlation_id` e `trace_id`.

```bash
# Terminal 1: o fluxo principal
docker compose logs -f --tail 0 pagamentos pagamentos-worker notificacoes-worker avaliacoes avaliacoes-worker

# Terminal 2: o mock da logística (quem avisa a entrega) e a API de notificações
docker compose logs -f --tail 0 mock-logistica notificacoes

# Terminal 3: livre, para os comandos da demo de resiliência
```

Se preferir apenas um terminal, o mínimo é
`docker compose logs -f pagamentos notificacoes-worker avaliacoes`.

## 3. Ordem das requests (coleção `delivery-financeiro`)

A coleção gera um `correlation_id` no formato `demo-<código>` na primeira execução e o manda em
todas as requests no header `X-Correlation-ID`. Rode **na ordem das pastas**, request por request
(ou a pasta inteira no Runner). A request "Pedido para cartão" cria os pedidos novos, então comece
sempre por `1. Autenticação` e `2. Pedidos`.

Copie o `demo-<código>` de uma linha de log e use-o para filtrar:
`docker compose logs --no-color | grep demo-<código>` (no PowerShell: `| Select-String demo-<código>`).

### Pastas 1 e 2: preparação

- `1. Autenticação`: as 4 requests `Token do cliente`, `Token do admin`, `Token do entregador` e `Token da loja`.
- `2. Pedidos`: as 5 requests `PUT` (cartão, cartão recusado, acima de R$ 5.000, Pix e resiliência).
- O que mostrar: nada de negócio aqui; só diga que o mock da Equipe 3 foi semeado com os pedidos.

### Pasta 3: Pagamentos

| Request | O que mostrar |
|---|---|
| `Cartão aprovado (final 0000)` | Resposta `201`. No terminal 1, a linha `requisicao_http` e a linha `pagamento_aprovado` de `pagamentos`, com o mesmo `correlation_id` |
| `Repetição com a mesma Idempotency-Key` | Mesma resposta, sem novo pagamento; no log, `idempotencia_resposta_repetida` (decisão: ADR 0006) |
| `Cartão recusado (final 0002)` | Pagamento recusado, log `pagamento_recusado` |
| `Acima de R$ 5.000 cai na antifraude` | Recusa pela regra de antifraude |
| `Detalhar o pagamento` | Estado final do pagamento |

Deixe `Pix aprovado` para o passo da resiliência (seção 4), ou rode agora se não for fazer essa demo.

### Pasta 4: Notificações

| Request | O que mostrar |
|---|---|
| `Inscrever webhook` | Assinatura criada (`assinatura_criada` no log). O `webhook_url` do ambiente local aponta para `host.docker.internal:9999`, onde nada escuta de propósito; mostre as falhas e retentativas em `Entregas do webhook` na pasta 7 |
| `E-mail de pagamento aprovado` | Consulta a API do Mailpit. Mostre também o e-mail **no Mailpit** (http://localhost:8025), assunto `Pagamento aprovado - pedido <id>`. No terminal 1, o caminho do evento: `evento_distribuido` e `email_enviado` do `notificacoes-worker`, com o mesmo `correlation_id` |
| `Notificações do cliente` | Lista do que foi notificado |

Mostre o **trace no Jaeger**: serviço `pagamentos` (ou `notificacoes`), **Find Traces**, e abra um
trace; copie o `trace_id` de uma linha de log para achar o mesmo trace. Ele liga a API, o
RabbitMQ e o worker.

### Pasta 5: Entrega

- `Logística conclui a entrega`: o mock da Equipe 4 avisa `entrega.concluida` em `POST /v1/eventos` de Notificações (terminal 2: `evento_externo_recebido`).
- `Pedido marcado como entregue`: o mock da Equipe 3 passa o pedido para entregue, o que libera a avaliação.

### Pasta 6: Avaliações

| Request | O que mostrar |
|---|---|
| `Avaliar o pedido` | `201` e `avaliacao_registrada` no log de `avaliacoes` |
| `Avaliar de novo dá 409` | Uma avaliação por pedido, erro no formato padrão |
| `Resumo do restaurante` | Média atualizada |

### Pasta 7: Disputa (saga de estorno)

| Request | O que mostrar |
|---|---|
| `Abrir disputa` | `disputa_aberta` no log |
| `Admin julga procedente` | `disputa_procedente`; em seguida `estorno_solicitado` e `estorno_registrado` (de `pagamentos`) e `estorno_processado` (de `avaliacoes`), todos com o mesmo `correlation_id`. O estorno é tentado na hora; só se falhar a saga repete depois de 30 s (`SAGA_ATRASO_INICIAL_SEGUNDOS`) |
| `Estorno aparece em Pagamentos` | O estorno registrado |
| `E-mail de disputa resolvida` | No Mailpit, assunto `Disputa procedente - pedido <id>` |
| `Entregas do webhook` | Tentativas de entrega ao webhook inscrito |

Mostre o diagrama [`sequencia-saga-disputa.md`](diagramas/sequencia-saga-disputa.md) enquanto fala da saga.

### Pasta 8: Resiliência do mock da Equipe 3

Prova de que uma dependência fora do ar vira erro amigável, sem derrubar o serviço.

1. `Derrubar o mock de pedidos` (`PUT {{pedidos}}/_controle/falha`).
2. `Pagamento com a Eq. 3 fora dá 503`: resposta `503` no formato padrão de erro; o circuit breaker aparece no log (`circuito_aberto`, `pedidos_resposta_inesperada` ou similar).
3. `Religar o mock de pedidos`.
4. `Sem token dá 401` e `Pagamento inexistente dá 404`: erros sempre no mesmo formato.

## 4. Demo de resiliência: worker de notificações fora do ar (aula 06)

Objetivo: mostrar que o e-mail **não se perde** quando o consumidor cai, porque o evento fica
guardado no RabbitMQ (e no outbox do banco) até alguém consumir.

1. No RabbitMQ (Queues and Streams), deixe visível a fila `notificacoes.eventos` com **Ready = 0**.
2. No terminal 3, derrube o worker:

   ```bash
   docker compose stop notificacoes-worker
   ```

3. No Postman, rode `Pix aprovado` (pasta 3). A API de Pagamentos responde `201` normalmente, pois
   o pagamento não depende do e-mail.
4. No painel do RabbitMQ, atualize: a fila `notificacoes.eventos` mostra **Ready = 1** (a mensagem
   `pagamento.aprovado` acumulada, com 0 consumidores). Faça outros pagamentos (por exemplo,
   repetindo a request com pedidos novos da pasta 2) para ver o número subir. No Mailpit, **nenhum**
   e-mail novo chegou.
5. Suba o worker de novo:

   ```bash
   docker compose start notificacoes-worker
   ```

6. No terminal 1, apareceram `evento_distribuido` e `email_enviado`. No RabbitMQ, **Ready** volta a
   0 e, no Mailpit, chegam todos os e-mails que ficaram pendentes, com assunto
   `Pagamento aprovado - pedido <id>`. Nenhuma mensagem foi perdida.

Complemento: se o envio do e-mail falhar (por exemplo, `docker compose stop mailpit`), a mensagem
passa pelas filas `notificacoes.emails.retry.1` a `.5` e, esgotadas as tentativas, vai para
`notificacoes.dlq` (ADR 0004). Suba o Mailpit (`docker compose start mailpit`) e mostre as
retentativas entregando.

## 5. Encerrando

```bash
docker compose --profile mocks down -v
```

O `-v` apaga os bancos e a fila; rode de novo `up -d --build` para recomeçar a demo do zero.

## 6. Plano B

- Sem Postman: `npx newman run docs/postman/delivery-financeiro.postman_collection.json -e docs/postman/local.postman_environment.json` roda tudo (não inclui a demo de parar o worker).
- URLs de produção para mostrar também: **a preencher depois do deploy** (veja [`deploy.md`](deploy.md)).
- Contexto para perguntas: [ADRs](adr/README.md), [diagramas](diagramas/README.md) e a [especificação](arquitetura/especificacao.md).
