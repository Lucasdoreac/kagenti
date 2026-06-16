$ErrorActionPreference = "Stop"

function Check($label, $block) {
    try { & $block; Write-Output " [OK] $label" }
    catch { Write-Output " [FAIL] $label — $($_.Exception.Message)" }
}

Write-Output "`n=== kagenti grounding-check ===`n"

# Ferramentas
Check "kubectl no PATH"  { Get-Command kubectl | Out-Null }
Check "gh no PATH"       { Get-Command gh | Out-Null }

# Cluster
Check "cluster acessivel" { kubectl get nodes --request-timeout=5s | Out-Null }

# Deployments prontos
Check "ai-agent-orchestrator ready" {
    $r = kubectl get deployment ai-agent-orchestrator -o jsonpath='{.status.readyReplicas}'
    if ($r -ne "1") { throw "readyReplicas=$r" }
}
Check "patient-records ready" {
    $r = kubectl get deployment patient-records -o jsonpath='{.status.readyReplicas}'
    if ($r -ne "1") { throw "readyReplicas=$r" }
}

# Endpoints funcionais
Check "agent /healthz" {
    $out = kubectl exec deploy/ai-agent-orchestrator -c python -- `
        python3 -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8080/healthz',timeout=5).read().decode())"
    if ($out -notmatch "ok") { throw $out }
}
Check "agent /triage patient_id=2" {
    $out = kubectl exec deploy/ai-agent-orchestrator -c python -- `
        python3 -c "
import json,urllib.request
req=urllib.request.Request('http://localhost:8080/triage',data=json.dumps({'patient_id':'2'}).encode(),headers={'Content-Type':'application/json'},method='POST')
print(urllib.request.urlopen(req,timeout=5).read().decode())"
    if ($out -notmatch "ALERTA") { throw $out }
}
Check "patient-records /patients" {
    $out = kubectl exec deploy/patient-records -- `
        python3 -c "import urllib.request; print(urllib.request.urlopen('http://localhost:80/patients',timeout=5).read().decode())"
    if ($out -notmatch "Ada Lovelace") { throw $out }
}

# Alertas de estado
$ns = kubectl get namespaces -o jsonpath='{.items[*].metadata.name}'
if ($ns -match "\bistio-system\b") { Write-Warning "[ALERTA] istio-system detectado — risco de conflito de sidecar" }
if ($ns -match "\bspire\b")        { Write-Warning "[ALERTA] spire detectado — identidades antigas podem contaminar" }

Write-Output "`n=== done ===`n"
