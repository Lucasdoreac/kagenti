#!/usr/bin/env bash
# Uso: OVERLAY=default ./scripts/deploy-client.sh
# Variáveis:
#   OVERLAY  - nome do overlay em deploy/overlays/ (default: "default")
#   CONTEXT  - kubectl context (default: current)

set -euo pipefail

OVERLAY="${OVERLAY:-default}"
CONTEXT="${CONTEXT:-$(kubectl config current-context)}"
OVERLAY_PATH="$(dirname "$0")/../deploy/overlays/${OVERLAY}"

if [[ ! -d "$OVERLAY_PATH" ]]; then
  echo "Overlay '${OVERLAY}' não encontrado em deploy/overlays/" >&2
  exit 1
fi

echo "[kagenti] deploying overlay=${OVERLAY} context=${CONTEXT}"
kubectl --context="${CONTEXT}" apply -k "${OVERLAY_PATH}"
kubectl --context="${CONTEXT}" rollout status deployment/ai-agent-orchestrator --timeout=120s
kubectl --context="${CONTEXT}" rollout status deployment/patient-records --timeout=120s
echo "[kagenti] done"
