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

Depois do primeiro deploy, cada merge na `main` atualiza a VM pelo pipeline de CD (seção 8).

## 1. Ativar o Azure for Students

1. Acesse <https://azure.microsoft.com/free/students> e entre com o e-mail institucional
   (`@upe.br`). A verificação é pelo e-mail: não pede cartão.
2. A assinatura **Azure for Students** dá US$ 100 de crédito por 12 meses. Confira o saldo em
   <https://www.microsoftazuresponsorships.com/Balance>.
3. Instale o Azure CLI (<https://learn.microsoft.com/cli/azure/install-azure-cli>) e entre:

   ```bash
   az login
   az account show --query "{assinatura:name, id:id}" --output table   # deve ser "Azure for Students"
   ```

Custo: uma B2s custa cerca de US$ 30–40/mês ligada, além do disco e do IP. Com
`az vm deallocate` (seção 7), a VM deixa de cobrar computação e o IP estático é mantido.

## 2. Gerar as chaves SSH

São dois pares:

- **Admin** (o seu): para entrar na VM como `azureuser`. Se você já tem `~/.ssh/id_ed25519.pub`,
  use esse.
- **Deploy** (do pipeline): usado só pelo GitHub Actions como usuário `deploy`. Gere um par novo,
  sem senha:

  ```bash
  ssh-keygen -t ed25519 -N "" -C deploy-financeiro-eq5 -f ~/.ssh/deploy-financeiro-eq5
  ```

  A chave pública (`.pub`) vai para a VM pelo cloud-init. A privada vai para o secret
  `SSH_CHAVE_PRIVADA` (seção 4) e não vai para nenhum outro lugar.

## 3. Criar a VM

Na raiz do repositório:

```bash
CHAVE_DEPLOY=~/.ssh/deploy-financeiro-eq5.pub ./infra/azure/criar-vm.sh
```

O script [`infra/azure/criar-vm.sh`](../infra/azure/criar-vm.sh) executa:

```bash
az group create --name rg-financeiro-eq5 --location eastus
az vm create --resource-group rg-financeiro-eq5 --name vm-financeiro-eq5 \
  --image Canonical:ubuntu-24_04-lts:server:latest --size Standard_B2s \
  --admin-username azureuser --ssh-key-values ~/.ssh/id_ed25519.pub --authentication-type ssh \
  --public-ip-sku Standard --nsg-rule SSH --os-disk-size-gb 30 \
  --custom-data <infra/cloud-init.yaml com a chave do deploy>
az vm open-port --resource-group rg-financeiro-eq5 --name vm-financeiro-eq5 --port 80 --priority 1010
az vm open-port --resource-group rg-financeiro-eq5 --name vm-financeiro-eq5 --port 443 --priority 1020
```

- **NSG:** libera só 22 (`--nsg-rule SSH`), 80 e 443. O cloud-init aplica as mesmas regras no
  `ufw`.
- **IP público:** estático (SKU Standard). O script imprime o IP e o domínio
  `financeiro-eq5.<ip>.sslip.io`. O sslip.io resolve qualquer `<algo>.<ip>.sslip.io` para
  `<ip>`, então não é preciso configurar DNS.
- **Região:** a assinatura de estudante pode restringir regiões. Se aparecer
  `RequestDisallowedByAzure` ou `SkuNotAvailable`, rode de novo com outra região, por exemplo
  `REGIAO=eastus2` ou `REGIAO=brazilsouth`. Antes, apague o grupo:
  `az group delete --name rg-financeiro-eq5`.
- **Outros ajustes:** `GRUPO`, `VM`, `TAMANHO` e `CHAVE_ADMIN` também são variáveis do script.

O [`infra/cloud-init.yaml`](../infra/cloud-init.yaml) leva alguns minutos depois que o
`az vm create` termina. Ele:

- instala o Docker Engine e o plugin compose (repositório oficial);
- cria o usuário `deploy` no grupo `docker`, só com login por chave;
- habilita `unattended-upgrades`;
- liga o `ufw` com 22/80/443, cria 2 GB de swap e o diretório `/opt/financeiro-eq5`.

Para conferir:

```bash
ssh azureuser@<ip> sudo cloud-init status --wait --long   # status: done
ssh -i ~/.ssh/deploy-financeiro-eq5 deploy@<ip> docker compose version
```

## 4. Segredos e configuração

Nenhum segredo real fica no repositório. Os valores ficam em **GitHub Secrets**, e o pipeline
de deploy grava o `.env` da VM a partir deles. O modelo com todas as variáveis, sem valores,
está em [`infra/.env.producao.example`](../infra/.env.producao.example).

### GitHub Secrets a cadastrar

Em *Settings → Secrets and variables → Actions → New repository secret*, ou pelo terminal com
`gh secret set <NOME>`.

| Secret | Para quê | Como gerar |
|---|---|---|
| `SSH_HOST` | IP público da VM | Saída do `criar-vm.sh` (seção 3) |
| `SSH_USUARIO` | Usuário de deploy na VM (`deploy`) | Criado pelo cloud-init (seção 3) |
| `SSH_CHAVE_PRIVADA` | Chave privada do par usado pelo pipeline | Conteúdo de `~/.ssh/deploy-financeiro-eq5` (seção 2) |
| `DOMINIO` | Domínio do Caddy, por exemplo `financeiro-eq5.<ip>.sslip.io` | A partir do IP |
| `BASIC_AUTH_USUARIO` | Login de `/jaeger` e `/mailpit` | Livre |
| `BASIC_AUTH_HASH` | Hash bcrypt da senha desse login | `docker run --rm caddy:2.10.2-alpine caddy hash-password --plaintext '<senha>'` |
| `TOKEN_SERVICO_SEGREDO` | Token de serviço interno (HS256), ≥ 32 caracteres | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `WEBHOOK_SEGREDO_CIFRAGEM` | Cifra os segredos dos webhooks, ≥ 32 caracteres e diferente do anterior | Mesmo comando |
| `RABBITMQ_USUARIO` / `RABBITMQ_SENHA` | Credenciais do RabbitMQ | Livre / mesmo comando |
| `PAGAMENTOS_DB_SENHA`, `NOTIFICACOES_DB_SENHA`, `AVALIACOES_DB_SENHA` | Senhas dos bancos | Mesmo comando |
| `JWKS_URL`, `IDENTIDADE_URL`, `PEDIDOS_URL` | APIs das Equipes 1 e 3 | Combinar com as equipes (#38 e #39) |
| `COMPOSE_PROFILES` | `mocks` enquanto as Equipes 1, 3 e 4 não estão no ar; vazio depois | Livre |
| `SSH_KNOWN_HOSTS` (opcional) | Fixa a chave do host da VM (seção 8) | `ssh-keyscan -t ed25519 <ip>` |
| `EMAIL_ADMIN`, `LOG_NIVEL`, `OTEL_HABILITADO`, `IDENTIDADE_CREDENCIAL` (opcionais) | Vazios usam o padrão | Livre |

- O pipeline lê tudo de `secrets.`, inclusive as URLs das outras equipes, que não são
  segredo: assim, um lugar só concentra a configuração.
- `IDENTIDADE_CREDENCIAL` só entra quando a Equipe 1 fornecer uma credencial de serviço.
- Quem gera um segredo cadastra-o direto no GitHub. O valor não passa por chat, issue ou commit.

### Cadastrar pelo terminal

`gh secret set` lê o valor da entrada padrão, então ele não fica no histórico do shell:

```bash
R=OcimarSchroederJR/delivery-financeiro
gh secret set SSH_HOST           -R $R --body "<ip>"
gh secret set SSH_USUARIO        -R $R --body deploy
gh secret set SSH_CHAVE_PRIVADA  -R $R < ~/.ssh/deploy-financeiro-eq5
gh secret set DOMINIO            -R $R --body "financeiro-eq5.<ip>.sslip.io"
for nome in TOKEN_SERVICO_SEGREDO WEBHOOK_SEGREDO_CIFRAGEM RABBITMQ_SENHA \
            PAGAMENTOS_DB_SENHA NOTIFICACOES_DB_SENHA AVALIACOES_DB_SENHA; do
  python -c "import secrets; print(secrets.token_urlsafe(48), end='')" | gh secret set "$nome" -R $R
done
gh secret set RABBITMQ_USUARIO   -R $R --body financeiro
gh secret set BASIC_AUTH_USUARIO -R $R --body admin
docker run --rm caddy:2.10.2-alpine caddy hash-password --plaintext '<senha-dos-paineis>' \
  | tr -d '\r\n' | gh secret set BASIC_AUTH_HASH -R $R
# Com os mocks (enquanto as outras equipes não estão no ar):
gh secret set JWKS_URL           -R $R --body http://mock-identidade:8001/.well-known/jwks.json
gh secret set IDENTIDADE_URL     -R $R --body http://mock-identidade:8001
gh secret set PEDIDOS_URL        -R $R --body http://mock-pedidos:8008
gh secret set COMPOSE_PROFILES   -R $R --body mocks
gh secret list -R $R
```

Guarde a senha dos painéis (`/jaeger` e `/mailpit`) num gerenciador de senhas. O GitHub
guarda só o hash.

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

## 5. Primeiro deploy manual

Faça uma vez, para conferir a VM antes de ligar o CD. Depois, o pipeline (seção 8) repete
estes passos a cada merge na `main`. Uma alternativa a este passo é rodar o workflow *Deploy* à
mão (*Actions → Deploy → Run workflow*), depois de cadastrar os Secrets.

### 5.1 Publicar as imagens no GHCR

Crie um token clássico em *GitHub → Settings → Developer settings → Personal access tokens*
com o escopo `write:packages`. Depois, na raiz do repositório:

```bash
echo "<token>" | docker login ghcr.io -u OcimarSchroederJR --password-stdin
TAG=$(git rev-parse HEAD)
for s in pagamentos notificacoes avaliacoes; do
  docker build -f services/$s/Dockerfile -t ghcr.io/ocimarschroederjr/$s:$TAG .
  docker push ghcr.io/ocimarschroederjr/$s:$TAG
done
docker build -f mocks/Dockerfile -t ghcr.io/ocimarschroederjr/mocks:$TAG .
docker push ghcr.io/ocimarschroederjr/mocks:$TAG
```

Os pacotes do GHCR nascem privados. A VM entra no GHCR com um token na hora do `pull`
(passo 5.3). Se preferir, deixe cada pacote público em *Package settings → Change visibility*,
já que o repositório é público.

### 5.2 Levar os arquivos e o `.env` para a VM

```bash
IP=<ip>
CHAVE=~/.ssh/deploy-financeiro-eq5
cp infra/.env.producao.example /tmp/env-producao   # preencha com os mesmos valores dos Secrets
scp -i $CHAVE infra/compose.prod.yaml infra/Caddyfile deploy@$IP:/opt/financeiro-eq5/
scp -i $CHAVE /tmp/env-producao deploy@$IP:/opt/financeiro-eq5/.env
ssh -i $CHAVE deploy@$IP chmod 600 /opt/financeiro-eq5/.env
rm /tmp/env-producao
```

No `.env`, use `TAG=<o mesmo SHA do passo 5.1>` e, com os mocks, `COMPOSE_PROFILES=mocks`.

### 5.3 Subir a pilha

```bash
ssh -i $CHAVE deploy@$IP
cd /opt/financeiro-eq5
echo "<token com read:packages>" | docker login ghcr.io -u OcimarSchroederJR --password-stdin
docker compose -f compose.prod.yaml pull
docker compose -f compose.prod.yaml up -d
docker logout ghcr.io
docker compose -f compose.prod.yaml ps
```

Na primeira requisição HTTPS, o Caddy obtém o certificado da Let's Encrypt para o domínio
sslip.io. Isso exige as portas 80 e 443 abertas, que o NSG já libera.

## 6. Verificar

```bash
D=financeiro-eq5.<ip>.sslip.io
for s in pagamentos notificacoes avaliacoes; do
  curl -fsS -o /dev/null -w "$s %{http_code}\n" https://$D/$s/saude/pronto   # 200
done
curl -s -o /dev/null -w "%{http_code}\n" https://$D/jaeger/                  # 401
curl -s -o /dev/null -w "%{http_code}\n" -u admin:<senha> https://$D/jaeger/ # 200
```

Swagger público:

- `https://financeiro-eq5.<ip>.sslip.io/pagamentos/docs`
- `https://financeiro-eq5.<ip>.sslip.io/notificacoes/docs`
- `https://financeiro-eq5.<ip>.sslip.io/avaliacoes/docs`

Se algo não responder, comece por `docker compose -f compose.prod.yaml ps` e
`docker compose -f compose.prod.yaml logs <servico>`. A tabela "O que o boot recusa em produção"
(seção 4) explica os erros de configuração mais comuns.

## 7. Operação

Todos os comandos rodam na VM, em `/opt/financeiro-eq5`.

| Tarefa | Comando |
|---|---|
| Ver os logs de um serviço | `docker compose -f compose.prod.yaml logs -f --tail 100 pagamentos` |
| Voltar para uma versão anterior | troque `TAG=` no `.env` pelo SHA anterior e rode `pull` + `up -d` |
| Reiniciar um serviço | `docker compose -f compose.prod.yaml restart avaliacoes-worker` |
| Liberar disco | `docker image prune -af --filter "until=168h"` |

No seu computador:

| Tarefa | Comando |
|---|---|
| Desligar a VM sem custo de computação (mantém o IP e o disco) | `az vm deallocate -g rg-financeiro-eq5 -n vm-financeiro-eq5` |
| Ligar de novo | `az vm start -g rg-financeiro-eq5 -n vm-financeiro-eq5` |
| Apagar tudo (VM, disco, IP, dados) | `az group delete --name rg-financeiro-eq5` |

## 8. Deploy contínuo (CD)

O workflow [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) roda a cada push na
`main`. Também dá para rodá-lo à mão em *Actions → Deploy → Run workflow*. Um deploy por vez
(`concurrency: deploy-producao`): um push novo espera o anterior terminar.

| Job / passo | O que faz |
|---|---|
| `imagem (<servico>)` | Build e push de `pagamentos`, `notificacoes`, `avaliacoes` e `mocks` para `ghcr.io/ocimarschroederjr/<nome>`, com as tags `<sha>` e `latest` (`packages: write`) |
| Gerar o `.env` | [`infra/gerar-env.sh`](../infra/gerar-env.sh) escreve `NOME='valor'` para cada variável do `.env.producao.example`, a partir dos Secrets, com `TAG=<sha>` |
| Validar o compose | `docker compose config` com esse `.env`: se faltar um Secret obrigatório, o job para **antes** de tocar na VM |
| Copiar | `scp` de `compose.prod.yaml`, `Caddyfile`, `implantar.sh` e `.env` para `/opt/financeiro-eq5` |
| Pull e up | [`infra/implantar.sh`](../infra/implantar.sh) na VM: login no GHCR com o `GITHUB_TOKEN` do job (recebido pela entrada padrão), `pull`, `up -d --remove-orphans`, `logout` e limpeza das imagens com mais de 7 dias |
| Smoke test | [`infra/smoke-test.sh`](../infra/smoke-test.sh) chama `https://$DOMINIO/<servico>/saude/pronto` dos 3 serviços, repetindo por até 2 minutos. A tabela vai para o resumo do job, e se algum não responder 200, o job fica vermelho |

Detalhes:

- **Chave do host SSH.** Sem o secret opcional `SSH_KNOWN_HOSTS`, o job aceita a chave que a VM
  apresentar no momento (`ssh-keyscan`). Para fixá-la, cadastre a saída de
  `ssh-keyscan -t ed25519 <ip>`, rodado da sua máquina logo depois de criar a VM:
  `ssh-keyscan -t ed25519 <ip> | gh secret set SSH_KNOWN_HOSTS`.
- **Imagens privadas.** Os pacotes do GHCR podem continuar privados: a VM faz login só durante o
  `pull`, com o token temporário do job.