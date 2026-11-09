# ADR 0007: `libs/plataforma` compartilhada, só código técnico

- **Status:** aceita

## Contexto

Os três serviços precisam das mesmas peças técnicas: envelope de evento, outbox e inbox, cliente HTTP com timeout e circuit breaker, verificação de JWT, logs com `correlation_id`, formato de erro, paginação, health checks, telemetria. Copiar isso em cada serviço faria os três divergirem e triplicaria os testes. Compartilhar demais, por outro lado, cria acoplamento: uma mudança na lib obriga a mexer em todos os serviços, e regra de negócio compartilhada vira um monólito disfarçado.

## Decisão

Existe um único pacote compartilhado, `libs/plataforma`, membro do workspace uv. Regra: **só código técnico, sem domínio**. Nada de "pagamento", "disputa" ou "notificação" dentro dele. Os mixins de outbox e inbox, por exemplo, são colunas genéricas; cada serviço declara a própria tabela e a própria `Base`.

Mitigações do acoplamento:

- A lib não importa nenhum serviço: a dependência é de mão única (o serviço importa `plataforma`).
- Interfaces pequenas e injetáveis (`Publicador`, `VerificadorDeToken`) em vez de herança profunda.
- A lib tem testes próprios (unitários, de API e de integração com Postgres e RabbitMQ reais).
- Código de apoio a testes (`plataforma.testes`) fica separado e é apagado das imagens de produção; um teste falha se código de produção o importar.
- Cada serviço tem o próprio esquema de banco, o próprio `config.py` (que herda a configuração base) e os próprios eventos.

## Alternativas consideradas

- **Copiar o código em cada serviço:** zero acoplamento, mas três versões de uma mesma correção de segurança.
- **Lib publicada com versão em registry:** correto em escala maior; excessivo para um monorepo de uma equipe.
- **Um serviço "base" chamado por HTTP:** troca uma chamada de função por uma de rede, sem ganho.

## Consequências

- Uma correção (por exemplo, no circuit breaker) vale para os três serviços de uma vez.
- Mudança incompatível na lib quebra os três; é preciso rodar os testes dos três pacotes para perceber.
- Os três serviços sobem e atualizam juntos; versões diferentes da lib por serviço não são suportadas.

**Onde está no código:** `libs/plataforma/src/plataforma/` (`outbox.py`, `inbox.py`, `envelope.py`, `cliente_http.py`, `circuit_breaker.py`, `auth.py`, `logs.py`, `correlation.py`, `erros.py`, `config.py`, `api/`), `libs/plataforma/src/plataforma/testes/isolamento.py` (guarda das importações de teste), `pyproject.toml` (`members` do workspace), `services/pagamentos/pyproject.toml` (dependência `plataforma`).
