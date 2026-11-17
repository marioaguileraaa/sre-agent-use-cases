<#
.SYNOPSIS
  Da al SRE Agent permisos de SOLO LECTURA sobre TODOS los AKS de un Management Group (o de una, varias o todas
  las suscripciones) en una sola ejecucion. Ya NO hay que pegar nada en la herramienta: descubre sola los AKS.

.DESCRIPTION
  Roles (todos de solo lectura; nunca se usan credenciales admin del cluster):
    - Reader                                          -> alcance (MG o cada suscripcion)
    - Cost Management Reader (opcional, -IncludeCost) -> alcance (costes por cluster)
    - Azure Kubernetes Service Cluster User Role      -> alcance (con -AksRolesAtScope) o cada AKS
    - Azure Kubernetes Service RBAC Reader            -> alcance (con -AksRolesAtScope) o cada AKS
  Asignados en el Management Group, los heredan todas sus suscripciones y los AKS que se creen en el futuro.

  Modos de alcance (elige uno; si no pones ninguno usa la suscripcion activa de "az login"):
    -ManagementGroupId <mg>     RECOMENDADO. Asigna los roles UNA vez en el Management Group.
    -AllSubscriptions           Todas las suscripciones habilitadas del tenant que ve tu "az login".
    -SubscriptionIds a,b,c      Lista explicita de suscripciones.
    -SubscriptionId <id>        Una sola suscripcion.

  Salida: lista de AKS encontrados por suscripcion, modo de autenticacion de cada uno y dos CSV
  (aks-clusters.csv y aks-auth-modes.csv). No genera nada que pegar.

  Requisitos de quien lo ejecuta: Owner, User Access Administrator o Role Based Access Control Administrator
  en el alcance elegido, y Azure CLI con "az login" en el tenant correcto.
  Volver a ejecutarlo es seguro: las asignaciones existentes no se duplican. -WhatIf muestra lo que haria sin cambiar nada.

.EXAMPLE
  # Recomendado: todo el Management Group, roles AKS a nivel de alcance y costes
  .\grant-aks-permissions.ps1 -IdentityClientId "<client-id>" -ManagementGroupId "<id-del-management-group>" -AksRolesAtScope -IncludeCost

.EXAMPLE
  # Ver lo que haria sin cambiar nada
  .\grant-aks-permissions.ps1 -IdentityClientId "<client-id>" -ManagementGroupId "<id-del-management-group>" -AksRolesAtScope -IncludeCost -WhatIf

.EXAMPLE
  # Una suscripcion concreta (por ejemplo, una nueva que no cuelga del Management Group)
  .\grant-aks-permissions.ps1 -IdentityClientId "<client-id>" -SubscriptionId "<id-suscripcion>" -AksRolesAtScope -IncludeCost
#>
param(
    [Parameter(Mandatory)][string]$IdentityClientId,
    [string]$ManagementGroupId,
    [switch]$AllSubscriptions,
    [string[]]$SubscriptionIds,
    [string]$SubscriptionId,
    [switch]$IncludeCost,
    [switch]$AksRolesAtScope,
    [switch]$WhatIf
)
$ErrorActionPreference = "Stop"

$ROLE_READER          = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
$ROLE_AKS_CLUSTERUSER = "4abbcc35-e782-43d8-92c5-2d3f1bd2253f"
$ROLE_AKS_RBACREADER  = "7f6c6a51-bcf8-42ba-9220-52d62157d7db"
$ROLE_COST_READER     = "72fafb9e-0641-4937-9268-a91bfd8191a3"
$REPORT_MAX_CLUSTERS  = 100
$failures = New-Object System.Collections.Generic.List[string]

function Invoke-AzQuiet {
    # En Windows PowerShell 5.1, "Stop" + stderr redirigido de az aborta el script: se comprueba $LASTEXITCODE.
    $ErrorActionPreference = "Continue"
    $out = & az @args 2>$null
    return $out
}

function Grant([string]$principalId, [string]$roleId, [string]$roleName, [string]$scope) {
    $exists = Invoke-AzQuiet role assignment list --assignee $principalId --scope $scope --role $roleId --include-inherited --query "[0].id" -o tsv
    if ($exists) { Write-Host "  [OK] $roleName ya asignado  ->  $scope (o heredado)" -ForegroundColor Green; return }
    if ($WhatIf) { Write-Host "  [WHATIF] Asignaria $roleName  ->  $scope" -ForegroundColor Magenta; return }
    $null = Invoke-AzQuiet role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal `
        --role $roleId --scope $scope --only-show-errors -o none
    if ($LASTEXITCODE -ne 0) {
        $failures.Add("$roleName -> $scope")
        Write-Host "  [ERROR] $roleName  ->  $scope (revisa tus permisos en ese alcance)" -ForegroundColor Red
    } else {
        Write-Host "  [OK] $roleName  ->  $scope" -ForegroundColor Green
    }
}

function Get-MgSubscriptions([string]$mg) {
    $url = "https://management.azure.com/providers/Microsoft.Management/managementGroups/$mg/descendants?api-version=2020-05-01"
    $subs = @()
    while ($url) {
        # En Windows az es un .cmd: se entrecomilla la URL para que cmd.exe no corte el nextLink en "&".
        $urlArg = if ($env:OS -eq "Windows_NT") { "`"$url`"" } else { $url }
        $raw = Invoke-AzQuiet rest --method get --url $urlArg -o json
        if ($LASTEXITCODE -ne 0 -or -not $raw) { throw "No se pudo leer el Management Group '$mg'. Revisa el ID (no el display name) y tus permisos." }
        $page = ($raw -join "`n") | ConvertFrom-Json
        $subs += @($page.value | Where-Object { $_.type -eq "Microsoft.Management/managementGroups/subscriptions" -or $_.type -eq "/subscriptions" } | ForEach-Object { $_.name })
        $url = $page.nextLink
    }
    return $subs
}

if ($WhatIf) { Write-Host "MODO -WhatIf: solo muestra lo que haria; no cambia nada." -ForegroundColor Magenta }

Write-Host "`n== 1. Tenant, identidad y suscripciones ==" -ForegroundColor Cyan
$tenantId = Invoke-AzQuiet account show --query tenantId -o tsv
if (-not $tenantId) { throw "No hay sesion de Azure CLI. Ejecuta primero: az login" }
$principalId = Invoke-AzQuiet ad sp show --id $IdentityClientId --query id -o tsv
if (-not $principalId) { throw "No se encuentra la identidad con Client ID $IdentityClientId en este tenant." }
Write-Host "  Tenant: $tenantId"
Write-Host "  Identidad SRE Agent: clientId=$IdentityClientId  principalId=$principalId"

$scopes = @()
if ($ManagementGroupId) {
    $scopes = @("/providers/Microsoft.Management/managementGroups/$ManagementGroupId")
    $subs = @(Get-MgSubscriptions $ManagementGroupId)
} elseif ($AllSubscriptions) {
    $subs = @(Invoke-AzQuiet account list --all --query "[?tenantId=='$tenantId' && state=='Enabled'].id" -o tsv)
} elseif ($SubscriptionIds) {
    $subs = @($SubscriptionIds | ForEach-Object { $_.Split(",") } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
} elseif ($SubscriptionId) {
    $subs = @($SubscriptionId)
} else {
    $subs = @(Invoke-AzQuiet account show --query id -o tsv)
}
$subs = @($subs | Where-Object { $_ } | ForEach-Object { $_.ToLower() } | Select-Object -Unique)
if (-not $subs) { throw "No se ha encontrado ninguna suscripcion en el alcance indicado." }
if (-not $scopes) { $scopes = @($subs | ForEach-Object { "/subscriptions/$_" }) }
Write-Host "  Suscripciones en alcance: $($subs.Count)"

Write-Host "`n== 2. Roles de lectura en el alcance ==" -ForegroundColor Cyan
foreach ($scope in $scopes) {
    Grant $principalId $ROLE_READER "Reader" $scope
    if ($IncludeCost) { Grant $principalId $ROLE_COST_READER "Cost Management Reader" $scope }
    if ($AksRolesAtScope) {
        Grant $principalId $ROLE_AKS_CLUSTERUSER "Azure Kubernetes Service Cluster User Role" $scope
        Grant $principalId $ROLE_AKS_RBACREADER  "Azure Kubernetes Service RBAC Reader" $scope
    }
}

Write-Host "`n== 3. Clusters AKS por suscripcion ==" -ForegroundColor Cyan
$subNames = @{}
$accounts = Invoke-AzQuiet account list --all -o json
if ($accounts) { foreach ($a in @(($accounts -join "`n") | ConvertFrom-Json | ForEach-Object { $_ })) { $subNames[$a.id.ToLower()] = $a.name } }
$found = @()
foreach ($sub in $subs) {
    $json = Invoke-AzQuiet aks list --subscription $sub --query "[].{name:name, rg:resourceGroup, id:id, managed:aadProfile.managed, azRbac:aadProfile.enableAzureRbac}" -o json
    $subName = $subNames[$sub]; if (-not $subName) { $subName = $sub }
    if ($LASTEXITCODE -ne 0) { $failures.Add("az aks list -> $sub"); Write-Host "  [ERROR] No se pudo listar AKS en $subName ($sub)" -ForegroundColor Red; continue }
    # ForEach-Object desenrolla el array (ConvertFrom-Json de Windows PowerShell 5.1 lo devuelve como un solo objeto).
    $list = @(($json -join "`n") | ConvertFrom-Json | ForEach-Object { $_ })
    Write-Host ("  {0,-45} {1,3} AKS" -f $subName, $list.Count)
    foreach ($aks in $list) {
        $found += [pscustomobject]@{ Suscripcion = $subName; SubscriptionId = $sub; ResourceGroup = $aks.rg; Cluster = $aks.name; Id = $aks.id
                                     Managed = [bool]$aks.managed; AzureRbac = [bool]$aks.azRbac }
    }
}
if (-not $found) { Write-Host "  [AVISO] No se ha encontrado ningun AKS en el alcance indicado." -ForegroundColor Yellow }

if ($found -and -not $AksRolesAtScope) {
    Write-Host "`n== 4. Roles AKS en cada cluster ==" -ForegroundColor Cyan
    foreach ($aks in $found) {
        Write-Host " $($aks.Cluster)"
        Grant $principalId $ROLE_AKS_CLUSTERUSER "Azure Kubernetes Service Cluster User Role" $aks.Id
        Grant $principalId $ROLE_AKS_RBACREADER  "Azure Kubernetes Service RBAC Reader" $aks.Id
    }
} elseif ($found) {
    Write-Host "`n== 4. Roles AKS ya asignados a nivel de alcance (cubre tambien clusters futuros) ==" -ForegroundColor Cyan
}

if ($found) {
    Write-Host "`n== 5. Resumen ==" -ForegroundColor Cyan
    $summary = foreach ($aks in $found) {
        $mode = if ($aks.Managed -and $aks.AzureRbac) { "OK: Entra ID + Azure RBAC" }
                elseif ($aks.Managed) { "AVISO: Entra ID con RBAC de Kubernetes -> workloads 'No evaluado'" }
                else { "AVISO: sin Entra ID -> solo parte ARM; workloads 'No evaluado'" }
        [pscustomobject]@{ Suscripcion = $aks.Suscripcion; ResourceGroup = $aks.ResourceGroup; Cluster = $aks.Cluster; LecturaKubernetes = $mode }
    }
    $summary | Format-Table -AutoSize -Wrap
    $found | Select-Object Suscripcion, SubscriptionId, ResourceGroup, Cluster | Export-Csv -Path "aks-clusters.csv" -NoTypeInformation -Encoding UTF8
    $summary | Export-Csv -Path "aks-auth-modes.csv" -NoTypeInformation -Encoding UTF8
    $subCount = @($found | Select-Object -ExpandProperty SubscriptionId -Unique).Count
    Write-Host "  $($found.Count) AKS en $subCount suscripciones. Detalle: aks-clusters.csv y aks-auth-modes.csv"
    if ($found.Count -gt $REPORT_MAX_CLUSTERS) {
        Write-Host "  [AVISO] Hay mas de $REPORT_MAX_CLUSTERS AKS: el informe de 'todos' admite hasta $REPORT_MAX_CLUSTERS; pedidlo por suscripcion." -ForegroundColor Yellow
    }
}

Write-Host "`nNO hay que pegar nada en la herramienta: descubre sola los AKS que la identidad puede leer." -ForegroundColor Yellow
Write-Host "Los permisos tardan 5-10 minutos en propagarse. Despues, en el chat: /agent aks-waf-live -> 'Lista los clusteres AKS por suscripcion'." -ForegroundColor Yellow
if ($failures.Count -gt 0) {
    Write-Host "`n$($failures.Count) operaciones fallaron:" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
