# ADR 0003: Síncrono vs assíncrono e entrada de eventos externos por HTTP

- **Status:** aceita

## Contexto

Os serviços conversam entre si e com as Equipes 1, 3 e 4. Algumas chamadas precisam da resposta para continuar (o resultado do pagamento, o estorno de uma disputa). Outras são efeitos colaterais que não podem travar quem chamou (e-mail, webhook). As outras equipes não são obrigadas a conhecer RabbitMQ.

## Decisão

- **HTTP** quando quem chama precisa da resposta para seguir. Exemplos: Pagamentos consulta o pedido; Avaliações chama o estorno em Pagamentos.
- **RabbitMQ** para efeitos colaterais. Pagamentos e Avaliações publicam eventos e seguem a vida; Notificações consome e entrega.
- **Eventos das outras equipes entram por `POST /v1/eventos`** em Notificações. O endpoint valida o envelope, grava no outbox e o relay o publica no broker. É o padrão Adapter da aula 07: o protocolo externo (HTTP) é traduzido para o interno (evento), e as outras equipes só precisam falar HTTP + JSON.
- O endpoint limita quem publica o quê: cada papel só emite os prefixos do próprio domínio, e prefixos como `pagamento` e `disputa` são reservados a nós.

## Alternativas consideradas

- **Tudo síncrono:** simples, mas uma notificação lenta ou fora do ar travaria o pagamento.
- **Tudo assíncrono:** o fluxo de pagamento precisa de resposta imediata, e a saga precisa saber se o estorno funcionou.
- **Expor o RabbitMQ às outras equipes:** exigiria cliente AMQP, credenciais e conhecimento da topologia em quatro equipes.

## Consequências

- Se o broker cair, as APIs continuam respondendo e os eventos esperam no outbox.
- Quem chama `POST /v1/eventos` recebe a confirmação de que o evento foi gravado, não de que a notificação foi entregue.
- Há dois estilos de falha para tratar: timeout, retry e circuit breaker no HTTP, e retry com DLQ no broker (ADR 0004).

**Onde está no código:** `services/notificacoes/src/notificacoes/adaptadores/http/rotas.py` (rota `/eventos`), `services/notificacoes/src/notificacoes/aplicacao/eventos_externos.py` (validação, `PREFIXOS_RESERVADOS`, `PREFIXOS_POR_PAPEL`), `libs/plataforma/src/plataforma/cliente_http.py`, `libs/plataforma/src/plataforma/circuit_breaker.py`, `services/avaliacoes/src/avaliacoes/adaptadores/clientes/pagamentos.py`.
