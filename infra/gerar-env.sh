#!/usr/bin/env bash
# Gera o .env de produção a partir das variáveis de ambiente (no CD, os GitHub Secrets).
#
# Uso: infra/gerar-env.sh [modelo] > .env
#   modelo: padrão infra/.env.producao.example
#
# Cada "NOME=" do modelo vira NOME='<valor de $NOME>'. As aspas simples deixam o valor
# literal para o compose (o hash bcrypt do basic auth tem "$"). Variável ausente vira
# vazia: o compose.prod.yaml recusa as obrigatórias com ${VAR:?}. Valores com aspa simples
# ou quebra de linha são recusados, porque não cabem nesse formato.
set -euo pipefail

modelo="${1:-$(dirname "${BASH_SOURCE[0]}")/.env.producao.example}"
[[ -f "$modelo" ]] || { echo "modelo não encontrado: $modelo" >&2; exit 1; }

mapfile -t nomes < <(grep -E '^[A-Z][A-Z0-9_]*=' "$modelo" | cut -d= -f1)
((${#nomes[@]})) || { echo "nenhuma variável em $modelo" >&2; exit 1; }

echo "# Gerado por infra/gerar-env.sh. Não edite na VM: o próximo deploy sobrescreve."
for nome in "${nomes[@]}"; do
  valor="${!nome-}"
  printf "%s='%s'\n" "$nome" "$valor"
done
