# ADR 0009: Deploy em VM única com Compose vs PaaS

- **Status:** aceita

## Contexto

O sistema precisa estar acessível pela Internet com HTTPS, e cada merge na `main` deve fazer deploy automático. A pilha tem 3 APIs, 3 workers, 3 migrações, 3 Postgres e 1 RabbitMQ, além de Jaeger, Mailpit e Caddy. O orçamento é o crédito do Azure for Students.

## Decisão

Uma única VM (Azure B2s, 2 vCPU, 4 GB, Ubuntu 24.04) rodando o mesmo Compose do desenvolvimento, em versão de produção (`compose.prod.yaml`). A VM é criada por `infra/azure/criar-vm.sh` com o `cloud-init.yaml` (Docker, usuário `deploy` só por chave, firewall em 22/80/443, swap de 2 GB). O Caddy termina o HTTPS e roteia por caminho (`/pagamentos`, `/notificacoes`, `/avaliacoes`); só ele publica portas. As imagens são construídas pelo pipeline, publicadas no GHCR com a tag do commit, e o deploy é um `docker compose pull && up -d` por SSH.

## Alternativas consideradas

- **PaaS por serviço (Render, Railway, Azure App Service):** deploy simples, mas cada serviço pediria seu Postgres gerenciado, e o RabbitMQ também precisaria de um provedor próprio. Seriam 3 bancos e 1 broker pagos individualmente, acima do crédito disponível, e os workers contariam como serviços extras.
- **Kubernetes (AKS):** coberto no ADR 0010.
- **Várias VMs:** isolamento melhor, custo e operação multiplicados sem tráfego que justifique.

## Consequências

- Custo baixo e paridade total entre desenvolvimento e produção: é o mesmo arquivo, com imagens no lugar do `build`.
- Ponto único de falha: se a VM cair, tudo cai. Não há alta disponibilidade.
- Recursos justos: 4 GB com swap. Não escala horizontalmente sem mudar a arquitetura.
- Rollback é trocar `TAG` no `.env` da VM; as imagens da última semana ficam guardadas.
- Segredos ficam em GitHub Secrets e são gravados no `.env` da VM durante o deploy.

**Onde está no código:** `infra/compose.prod.yaml`, `infra/Caddyfile`, `infra/cloud-init.yaml`, `infra/azure/criar-vm.sh`, `infra/implantar.sh`, `.github/workflows/deploy.yml`, `compose.yaml` (mesma pilha em desenvolvimento), `docs/deploy.md`.
