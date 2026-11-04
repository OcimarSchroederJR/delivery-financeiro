# Deploy em produção

Passo a passo reproduzível para colocar a Equipe 5 no ar numa VM do **Azure for Students**
(spec §7.3). A VM roda o [`infra/compose.prod.yaml`](../infra/compose.prod.yaml) atrás do Caddy,
com HTTPS automático em `financeiro-eq5.<ip>.sslip.io`.

| Etapa | Feita por | Frequência |
|---|---|---|
| 1. Ativar o Azure for Students | quem tem a conta | uma vez |
| 2. Gerar as chaves SSH | quem cria a VM | uma vez |
| 3. Criar a VM (`infra/azure/criar-vm.sh`) | quem cria a VM | uma vez |
| 4. Cadastrar os GitHub Secrets | quem cria a VM | uma vez (e ao trocar um segredo) |
| 5. Primeiro deploy manual | quem cria a VM | uma vez |
| 6. Verificar | qualquer pessoa | a cada deploy |

Depois do primeiro deploy, cada merge na `main` atualiza a VM pelo pipeline de CD (#36).

## Segredos e configuração

Nenhum segredo real fica no repositório. Os valores ficam em **GitHub Secrets**, e o pipeline
de deploy grava o `.env` da VM a partir deles. O modelo com todas as variáveis, sem valores,
está em [`infra/.env.producao.example`](../infra/.env.producao.example).

### GitHub Secrets a cadastrar

Em *Settings → Secrets and variables → Actions → New repository secret*, ou pelo terminal com
`gh secret set <NOME>`.

| Secret | Para quê | Como gerar |
|---|---|---|
| `SSH_HOST` | IP público da VM | Portal do Azure (#35) |
| `SSH_USUARIO` | Usuário de deploy na VM (`deploy`) | Criado pelo cloud-init (#35) |
| `SSH_CHAVE_PRIVADA` | Chave privada do par usado pelo pipeline | `ssh-keygen -t ed25519 -C deploy-financeiro-eq5 -f deploy` |
| `DOMINIO` | Domínio do Caddy, por exemplo `financeiro-eq5.<ip>.sslip.io` | A partir do IP |
| `BASIC_AUTH_USUARIO` | Login de `/jaeger` e `/mailpit` | Livre |
| `BASIC_AUTH_HASH` | Hash bcrypt da senha desse login | `docker run --rm caddy:2.10.2-alpine caddy hash-password --plaintext '<senha>'` |
| `TOKEN_SERVICO_SEGREDO` | Token de serviço interno (HS256), ≥ 32 caracteres | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `WEBHOOK_SEGREDO_CIFRAGEM` | Cifra os segredos dos webhooks, ≥ 32 caracteres e diferente do anterior | Mesmo comando |
| `RABBITMQ_USUARIO` / `RABBITMQ_SENHA` | Credenciais do RabbitMQ | Livre / mesmo comando |
| `PAGAMENTOS_DB_SENHA`, `NOTIFICACOES_DB_SENHA`, `AVALIACOES_DB_SENHA` | Senhas dos bancos | Mesmo comando |
| `JWKS_URL`, `IDENTIDADE_URL`, `PEDIDOS_URL` | APIs das Equipes 1 e 3 | Combinar com as equipes (#38 e #39) |

- As URLs das outras equipes não são segredo. Podem ir como *Variables* em vez de *Secrets*,
  desde que o pipeline as leia de `vars.` em vez de `secrets.`.
- `IDENTIDADE_CREDENCIAL` só entra quando a Equipe 1 fornecer uma credencial de serviço.
- Quem gera um segredo cadastra-o direto no GitHub. O valor não passa por chat, issue ou commit.

### O que o boot recusa em produção

Com `AMBIENTE=producao`, que o `infra/compose.prod.yaml` já define, a API e o worker de cada
serviço falham ao montar o `Config`. O container termina com o erro abaixo nos logs
(`docker compose logs <servico>`). A mensagem nomeia a variável, sem mostrar o valor recebido.

| Situação | Serviço | Erro |
|---|---|---|
| `TOKEN_SERVICO_SEGREDO` com menos de 32 caracteres | todos | `token_servico_segredo`: `String should have at least 32 characters` |
| `TOKEN_SERVICO_SEGREDO` igual ao padrão de desenvolvimento | todos | `TOKEN_SERVICO_SEGREDO usa o valor padrão de desenvolvimento` |
| `DATABASE_URL`, `RABBITMQ_URL` ou `JWKS_URL` ausente | todos | `Em produção, defina explicitamente: ...` |
| `PEDIDOS_URL` ausente | Pagamentos e Avaliações | idem |
| `PAGAMENTOS_URL` ausente | Avaliações | idem |
| `IDENTIDADE_URL` ausente | Notificações | idem |
| `WEBHOOK_SEGREDO_CIFRAGEM` ausente | Notificações | `WEBHOOK_SEGREDO_CIFRAGEM é obrigatório em produção` |

A regra fica em `libs/plataforma/src/plataforma/config.py`
(`CAMPOS_EXPLICITOS_EM_PRODUCAO`). Cada serviço estende a lista no próprio `config.py`.
