# ADR 0002: Arquitetura hexagonal com Repository e Unit of Work

- **Status:** aceita

## Contexto

Cada serviço tem regras que precisam de testes rápidos e confiáveis (estados do pagamento, regras da disputa, assinatura HMAC dos webhooks), mas depende de banco, broker e HTTP externo. A cobertura mínima exigida é de 75% e queremos testar o domínio sem subir infraestrutura.

## Decisão

Cada serviço segue a mesma divisão em três camadas, dentro de `src/<servico>/`:

- `dominio/`: entidades e regras puras, sem importar SQLAlchemy, FastAPI nem FastStream.
- `aplicacao/`: casos de uso e as **portas** (`Protocol`) de que eles precisam: repositórios, unidade de trabalho, relógio, clientes externos.
- `adaptadores/`: implementações das portas (SQLAlchemy, httpx, RabbitMQ, SMTP) e as rotas HTTP.

O Repository esconde o SQL atrás de métodos do domínio. A Unit of Work define a fronteira da transação: o estado e o evento do outbox são gravados e confirmados juntos (ADR 0005). A montagem das peças fica em `composicao.py`.

## Alternativas consideradas

- **Camadas clássicas (rota, serviço, ORM):** menos arquivos, mas as regras ficam misturadas ao ORM e os testes passam a exigir banco.
- **Lógica dentro dos modelos SQLAlchemy:** mais curto, mas acopla regra de negócio ao esquema de tabelas.
- **CQRS completo:** não há problema de leitura que o justifique (ADR 0010).

## Consequências

- Os testes unitários usam fakes em memória das portas e rodam em segundos; os de integração usam Postgres e RabbitMQ reais.
- Há mais arquivos e um pouco de cerimônia por funcionalidade.
- Os fakes ficam em `src/<servico>/testes/` para o mypy conferi-los contra as portas; o Dockerfile apaga esse pacote da imagem final.

**Onde está no código:** `services/pagamentos/src/pagamentos/dominio/`, `services/pagamentos/src/pagamentos/aplicacao/portas.py`, `services/pagamentos/src/pagamentos/adaptadores/db/repositorios.py`, `services/pagamentos/src/pagamentos/adaptadores/db/unidade_de_trabalho.py`, `services/pagamentos/src/pagamentos/composicao.py`, `services/pagamentos/src/pagamentos/testes/fakes.py`. Mesma estrutura em `services/notificacoes/` e `services/avaliacoes/`.
