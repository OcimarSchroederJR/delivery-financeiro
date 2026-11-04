#!/usr/bin/env bash
# Roda NA VM, no diretório onde estão compose.prod.yaml, Caddyfile e .env
# (/opt/financeiro-eq5). Chamado pelo pipeline de CD (.github/workflows/deploy.yml):
#
#   printf '%s' "$TOKEN_GHCR" | ssh deploy@<ip> 'GHCR_USUARIO=<usuario> bash /opt/financeiro-eq5/implantar.sh'
#
# O token de leitura do GHCR chega pela entrada padrão (não aparece em "ps" nem no histórico).
# Sem token na entrada, usa o login que já existir (ou pacotes públicos).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
compose=(docker compose -f compose.prod.yaml)

"${compose[@]}" config --quiet
"${compose[@]}" pull --quiet
"${compose[@]}" up -d --remove-orphans
"${compose[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
