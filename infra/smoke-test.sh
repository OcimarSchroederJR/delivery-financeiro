#!/usr/bin/env bash
# Smoke test da produção: GET https://<dominio>/<servico>/saude/pronto dos 3 serviços,
# repetindo até todos responderem 200 ou o prazo acabar (padrão 120 s).
#
# Uso: infra/smoke-test.sh <dominio> [opções extras do curl]
#   infra/smoke-test.sh financeiro-eq5.20.1.2.3.sslip.io
#   infra/smoke-test.sh localhost --insecure            # pilha de produção local (CA interna)
#
# Variáveis: SMOKE_PRAZO_SEGUNDOS (120), SMOKE_INTERVALO_SEGUNDOS (5).
# No GitHub Actions, o resultado também vai para o resumo do job ($GITHUB_STEP_SUMMARY).
set -euo pipefail

dominio="${1:?uso: $0 <dominio> [opções extras do curl]}"
shift
prazo="${SMOKE_PRAZO_SEGUNDOS:-120}"
intervalo="${SMOKE_INTERVALO_SEGUNDOS:-5}"
servicos=(pagamentos notificacoes avaliacoes)

declare -A codigo
pendentes=("${servicos[@]}")
fim=$((SECONDS + prazo))
tentativa=0
while true; do
  tentativa=$((tentativa + 1))
  restantes=()
  for servico in "${pendentes[@]}"; do
    codigo[$servico]="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$@" \
      "https://$dominio/$servico/saude/pronto" 2>/dev/null || true)"
    [[ "${codigo[$servico]}" == 200 ]] || restantes+=("$servico")
  done
  pendentes=("${restantes[@]+"${restantes[@]}"}")
  ((${#pendentes[@]} == 0)) && break
  ((SECONDS + intervalo < fim)) || break
  sleep "$intervalo"
done

if ((${#pendentes[@]})); then
  echo "Smoke test falhou: ${pendentes[*]} não respondeu 200 em ${prazo}s." >&2
  exit 1
fi
