# infra — produção da Equipe 5

Arquivos da produção (spec §7.3). Na VM, `compose.prod.yaml`, `Caddyfile` e `.env` ficam
lado a lado no mesmo diretório.

| Arquivo | Para quê |
|---|---|
| `compose.prod.yaml` | Pilha de produção: 3 APIs, 3 workers, 3 migrações, 3 Postgres, RabbitMQ, Mailpit, Jaeger e Caddy. Imagens `ghcr.io/ocimarschroederjr/<servico>:${TAG}`, sem `build`. |
| `Caddyfile` | Proxy reverso com HTTPS automático e roteamento por path. |
| `compose.prod.local.yaml` | Override só para testar na sua máquina: constrói as imagens a partir do código. Não vai para a VM. |
| `.env.local.example` | Variáveis fictícias para o teste local (`DOMINIO=localhost`). |
| `.env.producao.example` | Modelo do `.env` da VM, sem valores. |
| `cloud-init.yaml` | Prepara a VM: Docker, usuário `deploy`, `unattended-upgrades`, `ufw`, swap. |
| `azure/criar-vm.sh` | Cria a VM no Azure for Students com o cloud-init e o NSG (22, 80 e 443). |

## Rotas públicas

| Caminho | Destino | Observação |
|---|---|---|
| `/pagamentos/*` | `pagamentos:8000` | Prefixo removido; Swagger em `/pagamentos/docs` |
| `/notificacoes/*` | `notificacoes:8000` | Prefixo removido; Swagger em `/notificacoes/docs` |
| `/avaliacoes/*` | `avaliacoes:8000` | Prefixo removido; Swagger em `/avaliacoes/docs` |
| `/jaeger/` | `jaeger:16686` | Basic auth; prefixo mantido (`base_path=/jaeger`) |
| `/mailpit/` | `mailpit:8025` | Basic auth; prefixo mantido (`MP_WEBROOT=mailpit`) |
| `/<servico>` | redireciona para `/<servico>/docs` | |
| qualquer outro | 404 | |

Só o Caddy publica portas (80, 443 e 443/udp). APIs, bancos e RabbitMQ ficam na rede interna.
O Swagger funciona atrás do prefixo porque cada API recebe `ROOT_PATH=/<servico>`
(`libs/plataforma/src/plataforma/api/app.py`).

## Testar a produção na sua máquina

Pré-requisitos: Docker e as portas 80 e 443 livres.

```bash
cp infra/.env.local.example infra/.env
docker compose -f infra/compose.prod.yaml -f infra/compose.prod.local.yaml \
  --env-file infra/.env --profile mocks up -d --build
```

Com `DOMINIO=localhost` o Caddy emite o certificado pela CA interna: o navegador avisa e o
`curl` precisa de `-k`.

```bash
curl -k https://localhost/pagamentos/docs                    # 200 (Swagger)
curl -k https://localhost/pagamentos/saude/pronto            # 200
curl -k https://localhost/notificacoes/saude/pronto          # 200
curl -k https://localhost/avaliacoes/saude/pronto            # 200
curl -k https://localhost/jaeger/                            # 401
curl -k -u admin:senha-local-paineis https://localhost/jaeger/    # 200
curl -k -u admin:senha-local-paineis https://localhost/mailpit/   # 200
```

Para derrubar (apaga os volumes):

```bash
docker compose -f infra/compose.prod.yaml -f infra/compose.prod.local.yaml \
  --env-file infra/.env --profile mocks down -v
```

`up --wait` termina com erro porque os workers não têm healthcheck (é intencional, como no
compose local). Confira com `docker compose ... ps`.

## Variáveis

As marcadas com `${VAR:?}` no `compose.prod.yaml` são obrigatórias: o compose não sobe sem elas.

| Variável | O que é |
|---|---|
| `TAG` | Tag das imagens no GHCR (na VM, o SHA do commit) |
| `DOMINIO` | Domínio do Caddy, por exemplo `financeiro-eq5.<ip>.sslip.io` |
| `BASIC_AUTH_USUARIO` / `BASIC_AUTH_HASH` | Login de `/jaeger` e `/mailpit`; hash bcrypt |
| `TOKEN_SERVICO_SEGREDO` | Segredo do token de serviço interno (≥ 32 caracteres) |
| `WEBHOOK_SEGREDO_CIFRAGEM` | Chave que cifra os segredos dos webhooks (≥ 32 caracteres) |
| `RABBITMQ_USUARIO` / `RABBITMQ_SENHA` | Credenciais do RabbitMQ |
| `PAGAMENTOS_DB_SENHA`, `NOTIFICACOES_DB_SENHA`, `AVALIACOES_DB_SENHA` | Senhas dos bancos |
| `JWKS_URL`, `IDENTIDADE_URL`, `PEDIDOS_URL` | APIs das Equipes 1 e 3 (ou os mocks, com `--profile mocks`) |
| `EMAIL_ADMIN`, `LOG_NIVEL`, `OTEL_HABILITADO`, `SAGA_*` | Opcionais, com padrão |

Gerar segredos e o hash do basic auth:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
docker run --rm caddy:2.10.2-alpine caddy hash-password --plaintext '<senha>'
```

- **Senhas em URLs.** As senhas do RabbitMQ e dos bancos entram em `amqp://` e
  `postgresql://`. Use só letras, números, `-` e `_`; `token_urlsafe` já gera nesse formato.
- **Aspas no hash.** Escreva o hash entre aspas **simples** no `.env`
  (`BASIC_AUTH_HASH='$2a$14$...'`). Sem elas, o compose tenta interpolar os `$` do bcrypt.

Para criar a VM, cadastrar os GitHub Secrets, fazer o primeiro deploy e operar a produção, veja
[`docs/deploy.md`](../docs/deploy.md).
