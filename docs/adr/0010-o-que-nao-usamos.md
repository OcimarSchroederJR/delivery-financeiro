# ADR 0010: Tecnologias avaliadas e não adotadas

- **Status:** aceita

## Contexto

A ementa apresenta muitas tecnologias. O critério da equipe é não adicionar nenhuma que não resolva um problema real dos nossos três serviços. Abaixo, o que consideramos e por que ficou de fora. Se o problema aparecer, reabrimos a decisão.

## Decisão e justificativas

- **API Gateway:** serve para centralizar autenticação, roteamento e limites quando há muitos serviços e clientes. Aqui são três APIs e o Caddy já termina o HTTPS e roteia por caminho. A autenticação JWT está em cada serviço (ADR 0008). Um gateway seria mais um processo para a VM de 4 GB sem função nova.
- **Rate limiting:** protege contra abuso e picos de tráfego. O consumo é de uma turma e de mocks, não de clientes anônimos, e todas as rotas exigem token. A proteção que importa, contra repetição de operação financeira, é a `Idempotency-Key` (ADR 0006).
- **Service mesh:** resolve mTLS, observabilidade e retry entre dezenas de serviços em Kubernetes. Nossos serviços já têm timeout, retry e circuit breaker no cliente HTTP e traces no Jaeger, e rodam numa rede Docker privada.
- **gRPC:** ganha em desempenho e contrato tipado entre serviços internos de alto volume. Nossos consumidores são outras equipes que combinaram REST + JSON no documento V4; trocar o protocolo só nos isolaria.
- **GraphQL:** resolve o excesso ou a falta de campos para clientes com telas variadas. Os nossos recursos são poucos e fixos (pagamento, estorno, avaliação, disputa, notificação), e não há front-end nosso consultando vários recursos de uma vez.
- **Kafka:** é um log distribuído para alto volume, reprocessamento e vários consumidores com offsets. Nosso volume é baixo, não precisamos reler o histórico, e o RabbitMQ com topic exchange e DLQ cobre o roteamento (ADR 0004) com muito menos memória.
- **CDC/Debezium:** captura mudanças do banco para publicá-las. O outbox transacional resolve a escrita dupla sem Kafka Connect nem outro processo (ADR 0005).
- **CQRS:** separa modelos de leitura e escrita quando as consultas divergem muito dos comandos ou escalam de forma diferente. Nossas consultas são listagens simples, paginadas, no mesmo banco, e o repositório já isola o acesso (ADR 0002).
- **Kubernetes em produção:** orquestra muitas réplicas em vários nós. Temos uma VM com 6 processos de aplicação e a operação de um cluster custaria mais memória e atenção do que a própria aplicação (ADR 0009).
- **Terraform:** valeria para infraestrutura grande ou recriada com frequência. A nossa é uma VM, criada uma vez por `infra/azure/criar-vm.sh` e `infra/cloud-init.yaml`, que já são reproduzíveis e versionados.
- **Prometheus:** coleta métricas de série temporal para alertas. Para o escopo, logs JSON com `correlation_id` e traces no Jaeger bastam para provar a integração, e não há equipe de plantão que consuma alertas.

## Consequências

- Menos peças para operar, e a pilha cabe em uma VM de 4 GB.
- Quem esperar essas funções (limite de requisições, métricas, escala horizontal) não as encontra; cada uma vira decisão nova se surgir a necessidade.
- Os health checks `/saude/vivo` e `/saude/pronto` já deixam a porta aberta para orquestradores, se um dia forem necessários.

**Onde está no código:** esta decisão é sobre ausência. Em lugar delas: `infra/Caddyfile` (roteamento e HTTPS), `libs/plataforma/src/plataforma/circuit_breaker.py` e `cliente_http.py` (resiliência), `libs/plataforma/src/plataforma/telemetria.py` (OpenTelemetry), `libs/plataforma/src/plataforma/api/saude.py` (health checks), `compose.yaml` (pilha completa).
