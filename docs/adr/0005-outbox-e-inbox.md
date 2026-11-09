# ADR 0005: Transactional Outbox e Inbox

- **Status:** aceita

## Contexto

Quando um serviço muda o estado e precisa avisar os outros, são duas escritas em sistemas diferentes: banco e broker. É o problema da aula 06: "pedido salvo, notificação perdida" (ou o inverso: notificação enviada de um pedido que nunca foi salvo). Do outro lado, o RabbitMQ entrega "pelo menos uma vez", então o consumidor pode receber a mesma mensagem duas vezes.

## Decisão

- **Outbox:** o evento é gravado na tabela `outbox` na mesma transação da mudança de estado. Um relay no worker lê os pendentes em ordem, com `SELECT ... FOR UPDATE SKIP LOCKED`, publica no exchange e marca `publicado_em`. Se o broker falha, o evento fica pendente com `tentativas` e `ultimo_erro`, e o lote para para preservar a ordem. Cada publicação tem timeout de 5 s.
- **Inbox:** o consumidor insere o `mensagem_id` na tabela `inbox` (`INSERT ... ON CONFLICT DO NOTHING`) na mesma transação do efeito. Se já existia, a mensagem é confirmada sem refazer o efeito.
- O `mensagem_id` nasce no envelope do evento e viaja também como `message_id` do AMQP.

## Alternativas consideradas

- **Publicar direto depois do commit:** se o processo morrer entre os dois passos, o evento se perde.
- **Publicar antes do commit:** o consumidor pode agir sobre algo que sofreu rollback.
- **CDC/Debezium:** resolve o mesmo problema com mais infraestrutura (ADR 0010).
- **Transação distribuída (2PC):** o RabbitMQ não participa.

## Consequências

- Entrega **pelo menos uma vez**. A ordem é preservada dentro de cada serviço, sem garantia global.
- Há latência entre o commit e a publicação, de até o intervalo do relay (configurável).
- As tabelas `outbox` e `inbox` só crescem: não encontramos rotina de limpeza das linhas já publicadas ou processadas.
- O relay é seguro com várias réplicas por causa do `SKIP LOCKED`.
- Só Notificações consome do broker, então só ela tem `inbox`. Pagamentos e Avaliações têm apenas `outbox`.

**Onde está no código:** `libs/plataforma/src/plataforma/outbox.py` (`OutboxMixin`, `gravar_no_outbox`, `RelayOutbox`), `libs/plataforma/src/plataforma/inbox.py` (`registrar_na_inbox`), `libs/plataforma/src/plataforma/envelope.py`, `services/pagamentos/src/pagamentos/adaptadores/db/unidade_de_trabalho.py` (`RegistroDeEventosOutbox`), `services/notificacoes/src/notificacoes/adaptadores/db/modelos.py` (`MensagemProcessada`), `services/notificacoes/alembic/versions/0001_cria_outbox_e_inbox.py`.
