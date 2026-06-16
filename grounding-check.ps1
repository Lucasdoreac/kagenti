# grounding-check.ps1
# Força a parada imediata em caso de erro, garantindo zero workarounds.
$ErrorActionPreference = "Stop"

Write-Output "[GROUNDING] Iniciando sondagem determinística do ambiente..."

# 1. Validação de Ferramentas Essenciais no $env:PATH
$requiredBinaries = @("kubectl", "curl")
foreach ($bin in $requiredBinaries) {
    if ($null -eq (Get-Command $bin -ErrorAction SilentlyContinue)) {
        Write-Error "[FALHA ESTRUTURAL] Dependência crítica ausente: $bin. Altere o PATH no nível do SO. Abortando."
        exit 1
    }
}
Write-Output " [OK] Binários de infraestrutura detectados."

# 2. Validação de Conexão com o Control Plane do Kubernetes
Write-Output "[GROUNDING] Sondando soberania e acesso ao cluster..."
try {
    # Tenta resgatar os nós com timeout estrito para evitar hangs
    $nodes = kubectl get nodes --request-timeout="5s" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw $nodes
    }
} catch {
    Write-Error "[FALHA ESTRUTURAL] Perda de comunicação com o cluster Kubernetes ou Kubeconfig ausente. Causa raiz: $($_.Exception.Message)"
    exit 1
}
Write-Output " [OK] Cluster K8s acessível e responsivo."

# 3. Prevenção de Colisão e Idempotência (Verifica resquícios de instalações anteriores)
$namespaces = kubectl get namespaces -o jsonpath='{.items[*].metadata.name}'

if ($namespaces -match "\bistio-system\b") {
    Write-Warning "[ALERTA DE ESTADO] Namespace 'istio-system' detectado. Risco de violação de idempotência. Certifique-se de que não há state drift antes de injetar o istioctl."
}

if ($namespaces -match "\bspire\b") {
    Write-Warning "[ALERTA DE ESTADO] Namespace 'spire' detectado. Identidades criptográficas antigas podem contaminar a nova implantação."
}

# 4. Validação de Contexto de Diretório
if (-not (Test-Path ".\kagent-infra" -ErrorAction SilentlyContinue)) {
    Write-Output "[GROUNDING] Criando diretório de contenção local 'kagent-infra'..."
    New-Item -ItemType Directory -Force -Path ".\kagent-infra" | Out-Null
}
Set-Location ".\kagent-infra"

Write-Output "======================================================="
Write-Output "[GROUNDING SUCCESS] Ambiente validado. Vetor liberado."
Write-Output "======================================================="