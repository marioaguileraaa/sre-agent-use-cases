<#
.SYNOPSIS
  Da al SRE Agent los permisos de SOLO LECTURA que necesita el caso AKS Well-Architected Review.

.DESCRIPTION
  Asigna a la identidad administrada del SRE Agent:
    - Reader                                         -> suscripcion
    - Azure Kubernetes Service Cluster User Role     -> cada cluster AKS
    - Azure Kubernetes Service RBAC Reader           -> cada cluster AKS
    - Cost Management Reader (opcional, -IncludeCost)-> suscripcion
  Ningun rol permite modificar nada. Nunca se usan credenciales admin del cluster.
  Al final muestra el modo de autenticacion de cada cluster y el bloque de config para el .py.

  Requisitos de quien lo ejecuta: Owner, User Access Administrator o
  Role Based Access Control Administrator en la suscripcion, y Azure CLI con "az login".

.EXAMPLE
  # Lo normal: usa la suscripcion activa de "az login" y TODOS sus AKS
  .\grant-aks-permissions.ps1 -IdentityClientId "PEGAR-AQUI-EL-CLIENT-ID"

.EXAMPLE
  # Opcional: otra suscripcion y/o solo algunos clusters (resourceGroup/nombre)
  .\grant-aks-permissions.ps1 -IdentityClientId "<client-id>" -SubscriptionId "<sub-id>" `
      -Clusters "rg-aks-pro/aks-pro-01","rg-aks-pre/aks-pre-01"
#>
param(
    [Parameter(Mandatory)][string]$IdentityClientId,
    [string]$SubscriptionId,
    [string[]]$Clusters,
    [switch]$IncludeCost
)
$ErrorActionPreference = "Stop"

$ROLE_READER          = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
$ROLE_AKS_CLUSTERUSER = "4abbcc35-e782-43d8-92c5-2d3f1bd2253f"
$ROLE_AKS_RBACREADER  = "7f6c6a51-bcf8-42ba-9220-52d62157d7db"
$ROLE_COST_READER     = "72fafb9e-0641-4937-9268-a91bfd8191a3"

function Grant([string]$principalId, [string]$roleId, [string]$roleName, [string]$scope) {
    $null = az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal `
        --role $roleId --scope $scope --only-show-errors -o none
    if ($LASTEXITCODE -ne 0) { throw "No se pudo asignar '$roleName' en $scope" }
    Write-Host "  [OK] $roleName  ->  $scope" -ForegroundColor Green
}

Write-Host "`n== 1. Suscripcion e identidad ==" -ForegroundColor Cyan
if ($SubscriptionId) {
    az account set --subscription $SubscriptionId
    if ($LASTEXITCODE -ne 0) { throw "No hay acceso a la suscripcion $SubscriptionId (haz az login)." }
} else {
    $SubscriptionId = az account show --query id -o tsv
    if (-not $SubscriptionId) { throw "No hay sesion de Azure CLI. Ejecuta primero: az login" }
}
$subName = az account show --query name -o tsv
Write-Host "  Suscripcion: $subName ($SubscriptionId)"
$tenantId = az account show --query tenantId -o tsv
if (-not $Clusters) {
    $Clusters = @(az aks list --query "[].join('/', [resourceGroup, name])" -o tsv)
    if (-not $Clusters) { throw "No hay clusters AKS en la suscripcion $subName. Usa -SubscriptionId con la correcta." }
    Write-Host "  AKS detectados: $($Clusters -join ', ')"
}
$principalId = az ad sp show --id $IdentityClientId --query id -o tsv 2>$null
if (-not $principalId) { throw "No se encuentra la identidad con Client ID $IdentityClientId en este tenant." }
Write-Host "  Tenant: $tenantId"
Write-Host "  Identidad SRE Agent: clientId=$IdentityClientId  principalId=$principalId"

Write-Host "`n== 2. Roles en la suscripcion ==" -ForegroundColor Cyan
$subScope = "/subscriptions/$SubscriptionId"
Grant $principalId $ROLE_READER "Reader" $subScope
if ($IncludeCost) { Grant $principalId $ROLE_COST_READER "Cost Management Reader" $subScope }

Write-Host "`n== 3. Roles en cada cluster AKS ==" -ForegroundColor Cyan
$summary = @()
foreach ($c in $Clusters) {
    $parts = $c.Split("/")
    if ($parts.Count -ne 2) { throw "Formato incorrecto '$c'. Usa  resourceGroup/nombreCluster" }
    $rg, $name = $parts
    $aks = az aks show -g $rg -n $name --query "{id:id, aad:aadProfile}" -o json | ConvertFrom-Json
    if (-not $aks.id) { throw "No se encuentra el AKS $name en $rg" }
    Write-Host " $name"
    Grant $principalId $ROLE_AKS_CLUSTERUSER "Azure Kubernetes Service Cluster User Role" $aks.id
    Grant $principalId $ROLE_AKS_RBACREADER  "Azure Kubernetes Service RBAC Reader" $aks.id

    $managed = [bool]($aks.aad -and $aks.aad.managed)
    $azRbac  = [bool]($aks.aad -and $aks.aad.enableAzureRbac)
    $mode = if ($managed -and $azRbac) { "OK: Entra ID + Azure RBAC (lectura Kubernetes completa)" }
            elseif ($managed) { "AVISO: Entra ID con RBAC nativo de Kubernetes -> el RBAC Reader no aplica dentro del cluster; workloads saldran 'No evaluado' salvo ClusterRoleBinding de lectura" }
            else { "AVISO: cluster sin Entra ID -> solo se evalua la parte ARM; workloads 'No evaluado'" }
    $summary += [pscustomobject]@{ Cluster = $name; ResourceGroup = $rg; KubernetesLectura = $mode }
}

Write-Host "`n== 4. Modo de autenticacion de los clusters ==" -ForegroundColor Cyan
$summary | Format-Table -AutoSize -Wrap

Write-Host "== 5. Copia esto en el bloque CONFIGURACION de generate-aks-waf-report.py ==" -ForegroundColor Cyan
$costScope = if ($IncludeCost) { "node_resource_group" } else { "disabled" }
Write-Host "SUBSCRIPTION_ID = `"$SubscriptionId`""
Write-Host "TENANT_ID = `"$tenantId`""
Write-Host "MANAGED_IDENTITY_CLIENT_ID = `"$IdentityClientId`""
Write-Host "APPROVED_CLUSTERS = {"
foreach ($s in $summary) {
    Write-Host "    `"$($s.Cluster)`": {"
    Write-Host "        `"resource_group`": `"$($s.ResourceGroup)`","
    Write-Host "        `"environment`": `"PRODUCTION`","
    Write-Host "        `"kubernetes_enabled`": True,"
    Write-Host "        `"include_node_resource_group`": True,"
    Write-Host "        `"advisor_enabled`": True,"
    Write-Host "        `"approved_related_resource_ids`": [],"
    Write-Host "        `"approved_cost_resource_ids`": [],"
    Write-Host "        `"cost_scope`": `"$costScope`","
    Write-Host "        `"cost_timeframe`": `"month_to_date`","
    Write-Host "        `"requirements`": {},"
    Write-Host "    },"
}
Write-Host "}"
$enum = (@('""') + ($summary | ForEach-Object { "`"$($_.Cluster)`"" })) -join ","
Write-Host "`nEn el parametro cluster_name del tool, valores permitidos (enum): [$enum]" -ForegroundColor Yellow
Write-Host "Los permisos pueden tardar 5-10 minutos en propagarse.`n" -ForegroundColor Yellow
