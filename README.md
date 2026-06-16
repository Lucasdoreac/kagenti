# kagenti

Agente de triagem médica como serviço. Arquitetura: sidecar Envoy (OBridge) + agente Python + API mock de registros.

## Pré-requisitos

- `kind` + `kubectl` instalados
- Cluster Kind ativo (`kind create cluster`)

## Deploy em 5 minutos

```sh
# 1. Clone
git clone <repo-url> && cd kagenti

# 2. Deploy
kubectl apply -k deploy/overlays/default

# 3. Verifique
kubectl rollout status deployment/ai-agent-orchestrator
kubectl rollout status deployment/patient-records
```

## Testar

```sh
# Health check
kubectl exec deploy/ai-agent-orchestrator -c python -- \
  python3 -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8080/healthz').read().decode())"

# Triagem de paciente
kubectl exec deploy/ai-agent-orchestrator -c python -- \
  python3 -c "
import json, urllib.request
req = urllib.request.Request(
  'http://localhost:8080/triage',
  data=json.dumps({'patient_id': '2'}).encode(),
  headers={'Content-Type': 'application/json'}, method='POST')
print(urllib.request.urlopen(req).read().decode())"
```

## Fluxo de dados

```
caller → agente :8080 → Envoy :15001 → patient-records :80
```

## Estrutura

```
deploy/base/          # manifestos K8s — fonte única da verdade
deploy/overlays/      # configuração por cliente
src/agent/            # código do agente + Dockerfile
src/mock_records/     # API mock + Dockerfile
scripts/              # deploy-client.sh
```

## Novo cliente

```sh
cp -r deploy/overlays/default deploy/overlays/<cliente>
# edite deploy/overlays/<cliente>/kustomization.yaml
OVERLAY=<cliente> ./scripts/deploy-client.sh
```

## Kill switch (reverter sem downtime)

```sh
kubectl rollout undo deployment/ai-agent-orchestrator
kubectl rollout undo deployment/patient-records
```

## Remover tudo

```sh
kubectl delete -k deploy/overlays/default
```
