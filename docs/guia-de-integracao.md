# Guia de integração — Equipe 5 (Financeiro e Pós)

Este guia é para as outras equipes da turma. Ele explica como chamar os nossos serviços
(Pagamentos, Notificações e Avaliações) e o que esperamos de cada equipe. Os contratos completos
estão em [`openapi/`](openapi/) (HTTP) e [`asyncapi/`](asyncapi/) (eventos), e cada serviço tem
Swagger em `/docs`.

| Serviço | Local | Produção |
|---|---|---|
| Pagamentos | `http://localhost:8013` | `https://financeiro-eq5.<ip>.sslip.io/pagamentos` |
| Notificações | `http://localhost:8014` | `https://financeiro-eq5.<ip>.sslip.io/notificacoes` |
| Avaliações | `http://localhost:8015` | `https://financeiro-eq5.<ip>.sslip.io/avaliacoes` |

Para subir tudo na sua máquina, com mocks das Equipes 1, 3 e 4:

```bash
docker compose --profile mocks up -d --build
```

Os exemplos `curl` abaixo usam essa stack local e o [`jq`](https://jqlang.org/) para ler o JSON.
Também há uma coleção Postman com o fluxo inteiro em [`postman/`](postman/).

## Sumário

1. [Convenções gerais](#1-convenções-gerais)
2. [Equipe 1 — Identidade](#2-equipe-1--identidade)
3. [Equipe 3 — Checkout e Pedidos](#3-equipe-3--checkout-e-pedidos)
4. [Equipe 4 — Logística](#4-equipe-4--logística)
5. [Qualquer equipe — webhooks](#5-qualquer-equipe--webhooks)
6. [Catálogo de eventos](#6-catálogo-de-eventos)

## 1. Convenções gerais

São as convenções que propomos para a turma toda (spec §3.4).

- **Rotas** em português, no plural e com prefixo `/v1`: `/v1/pagamentos`, `/v1/disputas`.
  Ações são sub-recursos (`/v1/pagamentos/{id}/estornos`) ou `PATCH` de status.
- **JSON** em `snake_case`. Datas em ISO 8601, sempre em UTC: `2026-10-14T14:30:00Z`.
- **Dinheiro** em centavos, num inteiro com sufixo `_centavos`: `"valor_centavos": 4590` é R$ 45,90.
- **Erro** sempre no mesmo formato. `erro` e `mensagem` estão sempre presentes; `codigo` serve
  para tratar o caso no código e `correlation_id` serve para achar a requisição nos logs:

  ```json
  {"erro": true, "mensagem": "Pagamento recusado.", "codigo": "PAGAMENTO_RECUSADO", "correlation_id": "demo-123"}
  ```

  Alguns erros trazem campos extras, como `pagamento_id` e `motivo` no `PAGAMENTO_RECUSADO`.
- **Headers:**

  | Header | Quando |
  |---|---|
  | `Authorization: Bearer <jwt>` | Em todas as rotas, menos `/saude/*` e `/docs` |
  | `Idempotency-Key` | Obrigatório em `POST /v1/pagamentos` e `POST /v1/pagamentos/{id}/estornos` |
  | `X-Correlation-ID` | Opcional. Se você mandar, devolvemos o mesmo e propagamos para todos os eventos; se não mandar, geramos um |
  | `traceparent` | Opcional (W3C Trace Context). Se vier, o trace continua no nosso Jaeger |

- **Paginação** com `?pagina=1&tamanho=20` (máximo 100). A resposta vem assim:

  ```json
  {"itens": [], "pagina": 1, "tamanho": 20, "total": 57}
  ```

## 2. Equipe 1 — Identidade

### O que consumimos de vocês

| O quê | Para quê | Configuração do nosso lado |
|---|---|---|
| **JWKS** em `/.well-known/jwks.json` (ou um endpoint de validação) | Validar o JWT de todas as requisições, com a chave em cache | `JWKS_URL` |
| **Claim de papel** no JWT, com os valores `cliente`, `loja`, `entregador` e `admin` | Autorização por rota | `JWT_CLAIM_PAPEL` (hoje `papel`) |
| **`sub`** no JWT | Identificar o usuário (dono do pedido, da disputa etc.) | — |
| **`GET /perfis/{id}`** com o campo `email` | Saber para quem mandar o e-mail de cada evento | `IDENTIDADE_URL` |

Hoje usamos RS256. O emissor (`iss`) e a audiência (`aud`) são configuráveis por `JWT_*`, então
dá para trocar sem mexer no código.

### O que precisamos que vocês forneçam

- **Uma credencial de serviço** para o worker de Notificações consultar `GET /perfis/{id}`. O
  worker roda sem um usuário por trás, então não tem token de usuário para repassar. Pode ser
  client credentials ou outro formato que vocês já usem.

### Exemplo

No mock, qualquer `sub` e papel geram um token válido:

```bash
TOKEN=$(curl -s -X POST localhost:8001/tokens -H 'Content-Type: application/json' \
  -d '{"sub": "cliente-1", "papel": "cliente", "email": "cliente-1@exemplo.com"}' | jq -r .access_token)

curl -s localhost:8001/perfis/cliente-1
# {"id": "cliente-1", "nome": "Usuário cliente-1", "email": "cliente-1@exemplo.com", "papel": "cliente"}
```

## 3. Equipe 3 — Checkout e Pedidos

### O que consumimos de vocês

`GET /pedidos/{id}`, chamado por Pagamentos (para saber o valor) e por Avaliações (para saber se
o pedido foi entregue). Repassamos o token do usuário que fez a requisição. Os campos que lemos:

| Campo | Tipo | Uso |
|---|---|---|
| `cliente_id` | texto | O pedido precisa ser do `sub` do token |
| `restaurante_id` | texto | Vai para a avaliação e para o resumo do restaurante |
| `valor_total_centavos` | inteiro | É o valor cobrado. **Não aceitamos valor no corpo do pagamento** |
| `status` | texto | `entregue` libera avaliação; `cancelado` bloqueia pagamento |

Se os nomes ou os valores de `status` forem diferentes no serviço de vocês, ajustamos só o nosso
adaptador. Avisem a gente.

### Como chamar o pagamento no checkout

`POST /v1/pagamentos`, com o token do cliente e uma `Idempotency-Key` única por tentativa de
checkout. Repetir a mesma chave com o mesmo corpo devolve a mesma resposta (com o header
`Idempotency-Replayed: true`), então dá para repetir com segurança depois de um timeout.

```bash
curl -s -X POST localhost:8013/v1/pagamentos \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: checkout-ped-1-tentativa-1' \
  -d '{
        "pedido_id": "ped-1",
        "metodo": "cartao_credito",
        "cartao": {"numero": "4111111111110000", "titular": "Fulano de Tal", "validade": "12/30", "cvv": "123"}
      }'
```

Para Pix, o corpo é só `{"pedido_id": "ped-1", "metodo": "pix"}`. Os dados do cartão nunca são
gravados nem aparecem nos logs; guardamos só os 4 últimos dígitos.

| Resposta | O que significa | O que fazer |
|---|---|---|
| `201` | Aprovado. O corpo é o pagamento, com `id` e `status: "aprovado"` | Seguir com o pedido |
| `409 PAGAMENTO_RECUSADO` | Recusado. O corpo traz `pagamento_id` e `motivo` (`saldo_insuficiente`, `analise_antifraude`) | Mostrar ao cliente e permitir outra forma de pagamento |
| `409 PEDIDO_JA_PAGO` | O pedido já tem pagamento aprovado | Não cobrar de novo |
| `409 IDEMPOTENCY_EM_PROCESSAMENTO` | A mesma chave ainda está sendo processada | Esperar um pouco e repetir com a mesma chave |
| `422 PEDIDO_INEXISTENTE` | Não achamos o pedido em `GET /pedidos/{id}` | Conferir o `pedido_id` |
| `422 PEDIDO_CANCELADO` | O pedido está com status `cancelado` | Não cobrar |
| `422 IDEMPOTENCY_KEY_REUTILIZADA` | Mesma chave com corpo diferente | Gerar uma chave nova |
| `400 IDEMPOTENCY_KEY_AUSENTE` | Faltou o header | Mandar `Idempotency-Key` |
| `403` | O pedido é de outro cliente | — |
| `503 DEPENDENCIA_INDISPONIVEL` | Não conseguimos consultar o pedido, ou o gateway demorou | Repetir com a **mesma** chave: `5xx` não fica gravado |

Valores acima de R$ 5.000,00 são sempre recusados com `analise_antifraude`.

Para consultar depois: `GET /v1/pagamentos/{id}` ou `GET /v1/pagamentos?pedido_id=ped-1`.

### Como publicar eventos `pedido.*`

Se quiserem que o cliente receba e-mail ou webhook nas mudanças do pedido, publiquem em
`POST /v1/eventos` (Notificações). Hoje aceitamos `pedido.*` com token de papel `loja`; se vocês
preferirem uma credencial de sistema, combinamos. O envelope está na [seção 6](#6-catálogo-de-eventos).

```bash
TOKEN_LOJA=$(curl -s -X POST localhost:8001/tokens -H 'Content-Type: application/json' \
  -d '{"sub": "loja-1", "papel": "loja"}' | jq -r .access_token)

curl -s -X POST localhost:8014/v1/eventos \
  -H "Authorization: Bearer $TOKEN_LOJA" -H 'Content-Type: application/json' \
  -d "{
        \"mensagem_id\": \"$(uuidgen)\",
        \"tipo\": \"pedido.confirmado\",
        \"versao\": 1,
        \"ocorrido_em\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",
        \"correlation_id\": \"pedido-ped-1\",
        \"dados\": {\"pedido_id\": \"ped-1\", \"cliente_id\": \"cliente-1\", \"restaurante_id\": \"rest-1\"}
      }"
# 202 {"mensagem_id": "...", "status": "aceito"}
```

Mandar o mesmo `mensagem_id` de novo também responde `202`, com `"status": "duplicado"` e sem
processar duas vezes. Então dá para repetir em caso de dúvida.

## 4. Equipe 4 — Logística

Publiquem `entrega.*` em `POST /v1/eventos` (Notificações) com token de papel `entregador`. O
envelope é o mesmo da [seção 6](#6-catálogo-de-eventos). O `entrega.concluida` vira e-mail para o
cliente, então os `dados` precisam trazer pelo menos `pedido_id` e `cliente_id`:

```bash
TOKEN_ENTREGADOR=$(curl -s -X POST localhost:8001/tokens -H 'Content-Type: application/json' \
  -d '{"sub": "entregador-1", "papel": "entregador"}' | jq -r .access_token)

curl -s -X POST localhost:8014/v1/eventos \
  -H "Authorization: Bearer $TOKEN_ENTREGADOR" -H 'Content-Type: application/json' \
  -d "{
        \"mensagem_id\": \"$(uuidgen)\",
        \"tipo\": \"entrega.concluida\",
        \"versao\": 1,
        \"ocorrido_em\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",
        \"correlation_id\": \"entrega-ped-4\",
        \"dados\": {\"pedido_id\": \"ped-4\", \"cliente_id\": \"cliente-1\", \"entregador_id\": \"entregador-1\",
                  \"concluida_em\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}
      }"
```

Cada papel só publica os próprios tipos: `entregador` só `entrega.*`, `loja` só `pedido.*`. Fora
disso a resposta é `403 TIPO_DE_EVENTO_NAO_PERMITIDO`. Os tipos da Equipe 5 (`pagamento.*`,
`disputa.*` etc.) são reservados e dão `403 TIPO_DE_EVENTO_RESERVADO`.

## 5. Qualquer equipe — webhooks

Qualquer equipe pode receber os nossos eventos por webhook, sem precisar de RabbitMQ.

### Inscrever

```bash
curl -s -X POST localhost:8014/v1/webhooks \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"url": "https://sua-equipe.exemplo.com/webhooks/financeiro", "eventos": ["pagamento.*", "disputa.resolvida"]}'
```

- `eventos` aceita padrões com `*`: `pagamento.*` casa com `pagamento.aprovado`, `pagamento.estornado` etc.
- A resposta traz o **`segredo`**, que só aparece nessa vez. Guarde-o para validar as assinaturas.
- Em produção, a URL precisa ser `https` e pública. Localmente, `http` e host interno são aceitos.
- Uma inscrição de `admin` recebe todos os eventos. A de qualquer outro papel só recebe eventos em
  que `cliente_id`, `restaurante_id` ou `entregador_id` é o próprio usuário.
- `GET /v1/webhooks` lista as suas inscrições, `DELETE /v1/webhooks/{id}` remove uma e
  `GET /v1/webhooks/{id}/entregas` mostra cada tentativa de entrega (status HTTP, duração, erro).

### O que chega

Um `POST` na sua URL, com o envelope do evento no corpo e estes headers:

| Header | Conteúdo |
|---|---|
| `X-Assinatura` | `sha256=<HMAC-SHA256(segredo, "<timestamp>.<corpo>") em hexadecimal>` |
| `X-Assinatura-Timestamp` | Momento do envio, em segundos Unix |
| `X-Evento-Id` | O `mensagem_id` do evento |
| `X-Evento-Tipo` | O `tipo`, ex.: `pagamento.aprovado` |

### Validar a assinatura

Use o corpo **exatamente** como chegou (os bytes), antes de fazer o parse do JSON. Recuse
timestamps com mais de 5 minutos de diferença, para evitar replay.

```python
import hashlib
import hmac
import time


def assinatura_valida(segredo: str, corpo: bytes, timestamp: str, assinatura: str) -> bool:
    if abs(time.time() - int(timestamp)) > 300:
        return False
    esperado = hmac.new(segredo.encode(), f"{timestamp}.".encode() + corpo, hashlib.sha256)
    return hmac.compare_digest("sha256=" + esperado.hexdigest(), assinatura)
```

```javascript
const crypto = require("node:crypto");

function assinaturaValida(segredo, corpo, timestamp, assinatura) {
  if (Math.abs(Date.now() / 1000 - Number(timestamp)) > 300) return false;
  const esperado = "sha256=" + crypto.createHmac("sha256", segredo)
    .update(`${timestamp}.`).update(corpo).digest("hex");
  return esperado.length === assinatura.length
    && crypto.timingSafeEqual(Buffer.from(esperado), Buffer.from(assinatura));
}
```

### Garantias de entrega

- **Pelo menos uma vez.** O mesmo evento pode chegar mais de uma vez. Deduplique pelo
  `X-Evento-Id`.
- **Sucesso** é qualquer `2xx` em até 5 segundos. Responda rápido e processe depois, se precisar.
- **Até 6 tentativas:** a primeira e mais 5, com esperas de 1 s, 5 s, 30 s, 2 min e 10 min. Depois
  disso a entrega fica como `falhou` em `GET /v1/webhooks/{id}/entregas`.
- A ordem entre eventos diferentes não é garantida. Use o `ocorrido_em` se a ordem importar.

## 6. Catálogo de eventos

Todo evento, nosso ou de vocês, usa este envelope:

```json
{
  "mensagem_id": "4f1c2a9e-8b7d-4c1a-9f0e-2d3b4c5d6e7f",
  "tipo": "pagamento.aprovado",
  "versao": 1,
  "ocorrido_em": "2026-10-14T14:30:00Z",
  "correlation_id": "demo-123",
  "dados": {}
}
```

- `mensagem_id` é um UUID único por evento. É ele que usamos para deduplicar.
- `tipo` segue o formato `entidade.fato_no_passado`.
- Uma mudança incompatível em `dados` sobe a `versao`. Campos novos podem aparecer sem mudar a
  versão, então ignore os campos que você não conhece.
- Os campos `*_id` de `dados` são texto de 1 a 128 caracteres.

| Tipo | Produtor | `dados` | Vira e-mail para |
|---|---|---|---|
| `pagamento.aprovado` | Pagamentos | `pagamento_id, pedido_id, cliente_id, valor_centavos, metodo` | cliente |
| `pagamento.recusado` | Pagamentos | `pagamento_id, pedido_id, cliente_id, valor_centavos, motivo` | cliente |
| `pagamento.estornado` | Pagamentos | `pagamento_id, estorno_id, pedido_id, cliente_id, valor_centavos, motivo` | cliente |
| `avaliacao.registrada` | Avaliações | `avaliacao_id, pedido_id, restaurante_id, cliente_id, nota_restaurante, nota_entrega` | cliente |
| `disputa.aberta` | Avaliações | `disputa_id, pedido_id, cliente_id, motivo, valor_solicitado_centavos` | cliente |
| `disputa.resolvida` | Avaliações | `disputa_id, pedido_id, cliente_id, decisao, valor_estornado_centavos` | cliente |
| `disputa.estorno_falhou` | Avaliações | `disputa_id, pedido_id, motivo` | admin |
| `pedido.*` | Eq. 3, via `POST /v1/eventos` | definido pela Eq. 3 | — |
| `entrega.concluida` | Eq. 4, via `POST /v1/eventos` | `pedido_id, cliente_id, entregador_id, concluida_em` | cliente |
| outros `entrega.*` | Eq. 4, via `POST /v1/eventos` | definido pela Eq. 4 | — |

Em `pagamento.estornado`, `valor_centavos` é o valor **desse** estorno, não o total já estornado.

O schema de cada evento está em [`asyncapi/`](asyncapi/).

## Dúvidas e mudanças de contrato

Abram uma issue no repositório com o label `integracao-equipes`, ou falem com a Equipe 5. Mudanças
que quebrem o contrato combinado sempre passam por uma nova versão (`/v2` ou `versao` do evento).
