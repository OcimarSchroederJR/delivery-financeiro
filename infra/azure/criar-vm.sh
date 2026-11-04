#!/usr/bin/env bash
# Cria a VM de produção da Equipe 5 no Azure for Students (spec §7.3, docs/deploy.md).
#
# Uso (na raiz do repositório, depois de "az login"):
#   CHAVE_DEPLOY=~/.ssh/deploy-financeiro-eq5.pub ./infra/azure/criar-vm.sh
#
# Variáveis (todas com padrão, exceto CHAVE_DEPLOY):
#   CHAVE_DEPLOY  chave pública do par usado pelo pipeline (usuário "deploy")
#   CHAVE_ADMIN   sua chave pública, para o usuário administrador (padrão ~/.ssh/id_ed25519.pub)
#   GRUPO         resource group (padrão rg-financeiro-eq5)
#   REGIAO        região (padrão eastus; a assinatura de estudante pode restringir regiões)
#   VM            nome da VM (padrão vm-financeiro-eq5)
#   TAMANHO       tamanho da VM (padrão Standard_B2s: 2 vCPU, 4 GB)
#
# A VM sai com IP público estático (SKU Standard) e NSG liberando só 22, 80 e 443.
set -euo pipefail

: "${CHAVE_DEPLOY:?defina CHAVE_DEPLOY com o caminho da chave pública do pipeline}"
CHAVE_ADMIN="${CHAVE_ADMIN:-$HOME/.ssh/id_ed25519.pub}"
GRUPO="${GRUPO:-rg-financeiro-eq5}"
REGIAO="${REGIAO:-eastus}"
VM="${VM:-vm-financeiro-eq5}"
TAMANHO="${TAMANHO:-Standard_B2s}"
IMAGEM="Canonical:ubuntu-24_04-lts:server:latest"
ADMIN="azureuser"

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
modelo="$raiz/infra/cloud-init.yaml"

for arquivo in "$CHAVE_DEPLOY" "$CHAVE_ADMIN" "$modelo"; do
  [[ -f "$arquivo" ]] || { echo "arquivo não encontrado: $arquivo" >&2; exit 1; }
done
chave_deploy="$(tr -d '\r\n' < "$CHAVE_DEPLOY")"
[[ "$chave_deploy" == ssh-* ]] || { echo "CHAVE_DEPLOY não parece uma chave pública SSH" >&2; exit 1; }
[[ "$chave_deploy" != *[\|\&]* ]] || { echo "CHAVE_DEPLOY não pode conter '|' ou '&'" >&2; exit 1; }

# cloud-init com a chave do pipeline no lugar do marcador (o modelo versionado fica intacto).
custom_data="$(mktemp)"
trap 'rm -f "$custom_data"' EXIT
sed "s|__CHAVE_PUBLICA_DEPLOY__|$chave_deploy|" "$modelo" > "$custom_data"

echo ">> resource group $GRUPO em $REGIAO"
az group create --name "$GRUPO" --location "$REGIAO" --output none

echo ">> VM $VM ($TAMANHO, Ubuntu 24.04)"
az vm create \
  --resource-group "$GRUPO" \
  --name "$VM" \
  --image "$IMAGEM" \
  --size "$TAMANHO" \
  --admin-username "$ADMIN" \
  --ssh-key-values "$CHAVE_ADMIN" \
  --authentication-type ssh \
  --public-ip-sku Standard \
  --nsg-rule SSH \
  --os-disk-size-gb 30 \
  --custom-data "$custom_data" \
  --output none

echo ">> NSG: liberando 80 e 443 (o 22 já veio do --nsg-rule SSH)"
az vm open-port --resource-group "$GRUPO" --name "$VM" --port 80 --priority 1010 --output none
az vm open-port --resource-group "$GRUPO" --name "$VM" --port 443 --priority 1020 --output none

ip="$(az vm show --show-details --resource-group "$GRUPO" --name "$VM" --query publicIps --output tsv)"
cat <<EOF

VM criada. O cloud-init leva alguns minutos para instalar o Docker.

  IP público : $ip
  DOMINIO    : financeiro-eq5.$ip.sslip.io
  SSH (admin): ssh $ADMIN@$ip
  SSH (deploy): ssh -i ${CHAVE_DEPLOY%.pub} deploy@$ip

Conferir o fim do cloud-init:  ssh $ADMIN@$ip sudo cloud-init status --wait --long
Próximo passo: cadastrar os GitHub Secrets (docs/deploy.md, seção 4).
EOF
