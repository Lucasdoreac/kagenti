# CONTEXT.md — Estado do Projeto (handoff de agente)

## O que é este projeto
Harness de orquestração de agentes IA soberano (sem cloud). Motor de execução de skills com proxy Envoy (OBridge) como sidecar, arquitetura plugin de skills, e infraestrutura Kind bare metal.

**Repo:** https://github.com/Lucasdoreac/kagenti  
**Atenção:** Nome conflita com projeto Red Hat. Renomear está no ROADMAP.md.

---

## Cluster (Kind)

| Recurso | Estado |
|---|---|
| `ai-agent-orchestrator` | 2/2 Running (envoy + python) |
| `patient-records` | 1/1 Running |
| Service agente | ClusterIP :8080 |
| Service patient-records | ClusterIP :80 |
| ConfigMap `agent-code` | main.py + skills.json + llm.py + cleaner.py |
| ConfigMap `obridge-config` | Envoy config |

**Ollama:** não está rodando ainda. `host.docker.internal:11434` resolve para `192.168.65.254` mas está inacessível. Quando subir: `ollama pull gemma3:12b`.

---

## Endpoints do agente (porta 8080)

| Endpoint | Descrição |
|---|---|
| `GET /healthz` | `{"status":"ok"}` |
| `GET /skills` | catálogo completo |
| `GET /mcp` | manifest MCP tools/v1 |
| `POST /run` | execução direta de skill (requer `X-Delegation-Chain`) |
| `POST /chat` | loop ReAct via Ollama (requer Ollama rodando) |

**Segurança:** Todo POST sem `X-Delegation-Chain` → 403.

---

## Skills disponíveis (16 total)

### Upstream HTTP (via Envoy :15001)
- `get_patient(patient_id)` — busca registro
- `list_patients()` — lista todos

### Internal exec (sandbox /tmp/workspace)
- `execute_shell(command)` — bash no sandbox
- `write_file(filename, content)` — cria/sobrescreve arquivo
- `read_file(path)` — lê arquivo
- `list_dir(path)` — lista diretório
- `grep(pattern, path)` — busca regex em arquivos
- `glob(pattern)` — lista arquivos por padrão
- `git(command)` — git no workspace (push/reset bloqueados)
- `validate_code(code)` — ast.parse + ruff opcional
- `analyze_dependency_graph()` — grafo do catálogo

### Web
- `web_fetch(url)` — fetch e strip HTML, 8000 chars
- `web_search(query)` — DuckDuckGo Lite, 5 resultados

### Estado
- `memory_set(key, value)` — K/V em memória do processo
- `memory_get(key)` — recupera (key=* lista tudo)
- `todo_write(action, task)` — lista de tarefas (add/complete/list/clear)

---

## Arquivos-fonte

```
src/agent/
  main.py       — motor HTTP + todos os handlers
  skills.json   — catálogo declarativo com system_instruction
  llm.py        — cliente Ollama (urllib puro, zero deps)
  cleaner.py    — filtro de contexto por relevância de prompt
  Dockerfile    — python:3.11-slim + networkx

deploy/base/
  agent-configmap.yaml        — espelho de main.py + skills.json
  obridge-configmap.yaml      — Envoy com X-Delegation-Chain
  agent-deployment.yaml       — 2 containers: envoy + python
  patient-records-*.yaml      — API mock
```

---

## Padrão de deploy

```powershell
# ConfigMap (via arquivos fonte — fonte única da verdade):
cd kagenti
kubectl create configmap agent-code \
  --from-file=main.py=src/agent/main.py \
  --from-file=skills.json=src/agent/skills.json \
  --from-file=llm.py=src/agent/llm.py \
  --from-file=cleaner.py=src/agent/cleaner.py \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/ai-agent-orchestrator

# Tudo (kustomize):
kubectl apply -k deploy/overlays/default
```

---

## Teste rápido

```powershell
# Saúde
kubectl exec deploy/ai-agent-orchestrator -c python -- `
  python3 -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8080/healthz').read().decode())"

# Skill direta
kubectl exec deploy/ai-agent-orchestrator -c python -- python3 -c "
import json, urllib.request
H = {'Content-Type':'application/json','X-Delegation-Chain':'ai-agent-orchestrator'}
req = urllib.request.Request('http://localhost:8080/run',
  data=json.dumps({'skill':'web_search','params':{'query':'python agent tools'}}).encode(),
  headers=H, method='POST')
print(urllib.request.urlopen(req).read().decode())"
```

---

## Próximos passos (ROADMAP.md)

1. Subir Ollama + `gemma3:12b` → testar `/chat`
2. Renomear projeto (conflito com kagenti Red Hat)
3. Marca ludoc via BrandDocs (`ferdinandobons/brand-docs`)
4. CONTEXT.md no formato GSD Core (`open-gsd/gsd-core`)
5. AlignDev (`razr001/align-dev`) → gerar SKILL.md do projeto
