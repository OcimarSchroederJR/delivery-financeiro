# ADR 0006: `Idempotency-Key` em operações financeiras

- **Status:** aceita

## Contexto

Aula 03, timeout ambíguo: o cliente envia `POST /v1/pagamentos`, a conexão cai e ele não sabe se o pagamento foi feito. Repetir sem cuidado pode cobrar duas vezes. Duas requisições simultâneas para o mesmo pedido também não podem autorizar juntas.

## Decisão

`Idempotency-Key` é obrigatório nos `POST` com efeito financeiro (criar pagamento e criar estorno). O fluxo fica em `ExecutorIdempotente`:

1. **Reserva com dono.** A chave (escopo + chave) é reservada em transação própria, com PK composta. Cada reserva recebe um `dono` (UUID) novo. Chave já em processamento devolve 409; mesma chave com corpo diferente devolve 422; chave concluída devolve a resposta gravada.
2. **Resposta na mesma transação do efeito.** O caso de uso conclui a chave (status e corpo da resposta) antes do mesmo `commit` que grava o pagamento e o evento do outbox. Só vale para o dono atual: se a reserva foi reassumida por outra requisição, a conclusão falha, levanta `ReservaIdempotenciaPerdida` e o efeito sofre rollback.
3. **Falhas.** 4xx grava a resposta de erro. 5xx ou exceção inesperada remove a reserva (só a do dono), e o cliente pode repetir. Reserva abandonada por mais de 60 s pode ser reassumida; chaves com mais de 24 h expiram e o worker as apaga.
4. **Advisory lock por pedido.** Ao criar o pagamento, `pg_advisory_xact_lock(hashtext(pedido_id))` serializa as operações do mesmo pedido até o fim da transação. Duas chaves diferentes para o mesmo pedido não autorizam juntas: a segunda espera e então vê `PedidoJaPago`.
5. O hash do corpo é HMAC-SHA256 com segredo, porque o corpo pode conter número de cartão.

## Alternativas consideradas

- **Só unicidade em `pedido_id`:** evita duplicar, mas não devolve a resposta original nem cobre o estorno.
- **Cache em Redis:** infraestrutura nova e sem a atomicidade com o commit do pagamento.
- **Gravar a resposta depois do commit:** uma queda entre os dois passos reabre o timeout ambíguo.

## Consequências

- Repetir com a mesma chave é seguro, inclusive depois de queda do processo.
- A saga de disputa usa a chave `disputa-{id}`, então as retentativas do estorno não estornam duas vezes.
- A chamada ao gateway acontece dentro da transação com o lock; um gateway lento segura o lock daquele pedido (apenas dele).

**Onde está no código:** `services/pagamentos/src/pagamentos/aplicacao/idempotencia.py` (`ExecutorIdempotente`, `concluir_reserva`), `services/pagamentos/src/pagamentos/dominio/idempotencia.py` (`RegistroIdempotencia`, `dono`, prazos), `services/pagamentos/src/pagamentos/aplicacao/criar_pagamento.py` (lock e conclusão no mesmo commit), `services/pagamentos/src/pagamentos/adaptadores/db/repositorios.py` (`travar_pedido`, `RepositorioChavesIdempotenciaSql`), `services/pagamentos/alembic/versions/0003_adiciona_dono_das_chaves_de_idempotencia.py`.
