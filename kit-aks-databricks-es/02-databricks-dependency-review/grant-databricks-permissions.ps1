<#
.SYNOPSIS
  Da a la identidad del SRE Agent permisos de SOLO LECTURA sobre TODOS los workspaces de Azure Databricks
  de un Management Group (o de una, varias o todas las suscripciones) en una sola ejecucion.

.DESCRIPTION
  1) Azure (plano ARM), UNA vez en el alcance (Management Group o cada suscripcion):
       - Reader                                          -> configuracion del workspace, red y RG gestionado
       - Cost Management Reader (opcional, -IncludeCost) -> costes (DBU frente a infraestructura)
     Asignado en el Management Group lo heredan todas sus suscripciones, tambien las futuras.
  2) Descubre con Azure Resource Graph todos los workspaces del alcance (da igual en cuantas suscripciones esten).
  3) Dentro de CADA workspace (plano Databricks):
       - da de alta la identidad como service principal (Entra ID managed, workspace-access + databricks-sql-access,
         NUNCA admin);
       - CAN_VIEW en los jobs, pipelines y SQL warehouses que existan;
       - Unity Catalog: BROWSE + USE_CATALOG + USE_SCHEMA en los catalogos (solo metadatos, nunca SELECT ni ficheros).
     Si un workspace falla (sin permisos de admin, red privada...), lo apunta y sigue con el siguiente.
  4) Al final muestra un resumen por workspace y lo guarda en databricks-access-summary.csv.

  YA NO HAY QUE PEGAR NADA EN EL .py: la herramienta descubre sola los workspaces que la identidad puede leer.

  Quien lo ejecuta necesita:
    - Owner, User Access Administrator o Role Based Access Control Administrator en el alcance (paso 1);
    - Workspace Admin en los workspaces (paso 3). Los workspaces donde no lo sea quedan como "SIN ACCESO" en el resumen.
  Volver a ejecutarlo es seguro (no duplica nada). Conviene repetirlo de vez en cuando: los jobs, pipelines y
  warehouses nuevos no tienen CAN_VIEW hasta que se vuelve a ejecutar.

.EXAMPLE
  # Recomendado: todo el Management Group, con costes
  .\grant-databricks-permissions.ps1 -IdentityClientId "<client-id>" -ManagementGroupId "<id-del-management-group>" -IncludeCost

.EXAMPLE
  # Ver lo que haria sin cambiar nada
  .\grant-databricks-permissions.ps1 -IdentityClientId "<client-id>" -ManagementGroupId "<id-del-management-group>" -IncludeCost -WhatIf

.EXAMPLE
  # Solo algunas suscripciones, o solo algunos workspaces ("suscripcion/resourceGroup/nombre")
  .\grant-databricks-permissions.ps1 -IdentityClientId "<client-id>" -SubscriptionIds "<sub-1>","<sub-2>" -IncludeCost
  .\grant-databricks-permissions.ps1 -IdentityClientId "<client-id>" -ManagementGroupId "<mg>" -Workspaces "<sub>/<rg>/<workspace>"
#>
param(
    [Parameter(Mandatory = $true)][string]$IdentityClientId,
    [string]$ManagementGroupId,
    [switch]$AllSubscriptions,
    [string[]]$SubscriptionIds,
    [string]$SubscriptionId,
    [string[]]$Workspaces,
    [switch]$IncludeCost,
    [switch]$SkipDatabricksGrants,
    [switch]$SkipUnityCatalog,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
$DatabricksResource = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"
$ReaderRoleId = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
$CostReaderRoleId = "72fafb9e-0641-4937-9268-a91bfd8191a3"
$SkipCatalogs = @("system", "hive_metastore", "samples", "__databricks_internal")
$MaxWorkspaces = 1000

function Write-Step($t) { Write-Host "`n== $t ==" -ForegroundColor Cyan }
function Write-Ok($t) { Write-Host "  [OK] $t" -ForegroundColor Green }
function Write-Warn2($t) { Write-Host "  [AVISO] $t" -ForegroundColor Yellow }
function Write-Plan($t) { Write-Host "  [WHATIF] $t" -ForegroundColor Magenta }
function Invoke-AzQuiet {
    # En Windows PowerShell 5.1, "Stop" + stderr redirigido de az aborta el script: se comprueba $LASTEXITCODE.
    $ErrorActionPreference = "Continue"
    $out = & az @args 2>$null
    return $out
}
function ConvertFrom-AzJson($raw) { if ($raw) { return (($raw -join "`n") | ConvertFrom-Json) } return $null }

if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw "Falta Azure CLI (az). Instalalo y ejecuta 'az login'." }
if ($WhatIf) { Write-Host "MODO -WhatIf: solo muestra lo que haria; no cambia nada." -ForegroundColor Magenta }

Write-Step "Contexto"
$acct = ConvertFrom-AzJson (Invoke-AzQuiet account show -o json)
if (-not $acct) { throw "No hay sesion de Azure CLI. Ejecuta 'az login' en el tenant correcto." }
$TenantId = $acct.tenantId
Write-Ok "Tenant: $TenantId (usuario $($acct.user.name))"
$sp = ConvertFrom-AzJson (Invoke-AzQuiet ad sp show --id $IdentityClientId -o json)
if (-not $sp) { throw "No encuentro la identidad con Client ID $IdentityClientId en este tenant. Copia el Client ID de la identidad administrada del agente (portal de Azure > grupo de recursos del agente > identidad id-... > Overview)." }
$PrincipalId = $sp.id
$SpName = $sp.displayName
Write-Ok "Identidad del agente: $SpName (objectId $PrincipalId)"

# ---- Alcance -------------------------------------------------------------------------------
$scopes = @()
$argScope = @{}
if ($ManagementGroupId) {
    $scopes = @("/providers/Microsoft.Management/managementGroups/$ManagementGroupId")
    $argScope = @{ managementGroups = @($ManagementGroupId) }
    Write-Ok "Alcance: Management Group $ManagementGroupId (todas sus suscripciones, tambien las futuras)"
} elseif ($AllSubscriptions) {
    $subs = @(Invoke-AzQuiet account list --all --query "[?tenantId=='$TenantId' && state=='Enabled'].id" -o tsv)
    $scopes = @($subs | ForEach-Object { "/subscriptions/$_" })
    $argScope = @{ subscriptions = @($subs) }
    Write-Ok "Alcance: $($subs.Count) suscripciones habilitadas del tenant"
} else {
    $subs = @()
    if ($SubscriptionIds) { $subs = @($SubscriptionIds | ForEach-Object { $_.Split(",") } | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
    elseif ($SubscriptionId) { $subs = @($SubscriptionId) }
    else { $subs = @($acct.id) }
    $subs = @($subs | ForEach-Object { $_.ToLower() } | Select-Object -Unique)
    $scopes = @($subs | ForEach-Object { "/subscriptions/$_" })
    $argScope = @{ subscriptions = @($subs) }
    Write-Ok "Alcance: $($subs.Count) suscripcion(es)"
}
if (-not $scopes) { throw "No se ha encontrado ningun alcance (Management Group o suscripcion)." }

# ---- 1. Roles de Azure ----------------------------------------------------------------------
$failures = New-Object System.Collections.Generic.List[string]
function Grant-Role($roleId, $roleName, $scope) {
    $exists = Invoke-AzQuiet role assignment list --assignee $PrincipalId --scope $scope --role $roleId --include-inherited --query "[0].id" -o tsv
    if ($exists) { Write-Ok "$roleName ya asignado en $scope (o heredado)"; return }
    if ($WhatIf) { Write-Plan "Asignaria $roleName en $scope"; return }
    $null = Invoke-AzQuiet role assignment create --assignee-object-id $PrincipalId --assignee-principal-type ServicePrincipal --role $roleId --scope $scope --only-show-errors -o none
    if ($LASTEXITCODE -ne 0) { Write-Warn2 "No se pudo asignar $roleName en $scope (hace falta Owner, User Access Administrator o Role Based Access Control Administrator)"; $failures.Add("$roleName en $scope") }
    else { Write-Ok "$roleName asignado en $scope" }
}
Write-Step "1/3 Azure: roles de lectura en el alcance"
foreach ($scope in $scopes) {
    Grant-Role $ReaderRoleId "Reader" $scope
    if ($IncludeCost) { Grant-Role $CostReaderRoleId "Cost Management Reader" $scope }
}

# ---- 2. Descubrir workspaces con Azure Resource Graph -------------------------------------
Write-Step "2/3 Workspaces de Databricks en el alcance (Azure Resource Graph)"
$query = "resources | where type =~ 'microsoft.databricks/workspaces' | project id, name, resourceGroup, subscriptionId, " +
         "workspaceUrl = tostring(properties.workspaceUrl), sku = tostring(sku.name), publicNetworkAccess = tostring(properties.publicNetworkAccess) " +
         "| order by subscriptionId asc, name asc"
$rows = @()
$skip = $null
do {
    $body = @{ query = $query; options = @{ '$top' = 1000; resultFormat = "objectArray" } } + $argScope
    if ($skip) { $body.options['$skipToken'] = $skip }
    $tmp = [IO.Path]::GetTempFileName()
    [IO.File]::WriteAllText($tmp, ($body | ConvertTo-Json -Depth 6 -Compress), (New-Object Text.UTF8Encoding $false))
    $raw = Invoke-AzQuiet rest --method post --url "https://management.azure.com/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01" --body "@$tmp" -o json
    $code = $LASTEXITCODE
    Remove-Item $tmp -ErrorAction SilentlyContinue
    if ($code -ne 0 -or -not $raw) { throw "Azure Resource Graph no respondio. Comprueba que tu usuario puede leer el alcance indicado." }
    $page = ($raw -join "`n") | ConvertFrom-Json
    $rows += @($page.data | ForEach-Object { $_ })
    $skip = $page.'$skipToken'
} while ($skip -and $rows.Count -lt $MaxWorkspaces)

if ($Workspaces) {
    $wanted = @($Workspaces | ForEach-Object { $_.Trim().ToLower() })
    $rows = @($rows | Where-Object {
        $wanted -contains ("$($_.subscriptionId)/$($_.resourceGroup)/$($_.name)").ToLower() -or $wanted -contains ("$($_.resourceGroup)/$($_.name)").ToLower()
    })
}
if (-not $rows) { throw "No se ha encontrado ningun workspace de Databricks en el alcance indicado." }
$subNames = @{}
foreach ($s in @(ConvertFrom-AzJson (Invoke-AzQuiet account list --all -o json) | ForEach-Object { $_ })) { $subNames[$s.id.ToLower()] = $s.name }
Write-Ok "$($rows.Count) workspaces en $(@($rows | Select-Object -ExpandProperty subscriptionId -Unique).Count) suscripciones"
foreach ($w in $rows) {
    $sn = $subNames[$w.subscriptionId.ToLower()]; if (-not $sn) { $sn = $w.subscriptionId }
    Write-Host ("    {0,-40} {1,-30} {2}" -f $w.name, $sn, $w.workspaceUrl)
}

# ---- 3. Dentro de cada workspace ------------------------------------------------------------
$summary = New-Object System.Collections.Generic.List[object]
if ($SkipDatabricksGrants) {
    Write-Step "3/3 Databricks: omitido (-SkipDatabricksGrants). La parte interna de los workspaces saldra 'sin acceso'."
} else {
    Write-Step "3/3 Databricks: alta de la identidad en cada workspace"
    $token = Invoke-AzQuiet account get-access-token --resource $DatabricksResource --query accessToken -o tsv
    if (-not $token) { throw "No se pudo obtener un token de Azure Databricks con tu usuario." }
    $hdr = @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" }

    function Invoke-Dbx($wsHost, $method, $path, $body) {
        $uri = "https://$wsHost$path"
        if ($body) { return Invoke-RestMethod -Method $method -Uri $uri -Headers $hdr -Body ($body | ConvertTo-Json -Depth 10) -TimeoutSec 60 -ErrorAction Stop }
        return Invoke-RestMethod -Method $method -Uri $uri -Headers $hdr -TimeoutSec 60 -ErrorAction Stop
    }
    function Get-HttpCode($err) {
        try { return [int]$err.Exception.Response.StatusCode } catch { return 0 }
    }
    function Grant-View($wsHost, $objType, $id, $label) {
        if ($WhatIf) { return $true }
        $acl = @{ access_control_list = @(@{ service_principal_name = $IdentityClientId; permission_level = "CAN_VIEW" }) }
        try { Invoke-Dbx $wsHost "PATCH" "/api/2.0/permissions/$objType/$id" $acl | Out-Null; return $true }
        catch { Write-Warn2 "CAN_VIEW en $label fallo: $($_.Exception.Message)"; return $false }
    }

    $i = 0
    foreach ($w in $rows) {
        $i++
        $h = $w.workspaceUrl
        $sn = $subNames[$w.subscriptionId.ToLower()]; if (-not $sn) { $sn = $w.subscriptionId }
        $row = [ordered]@{ Workspace = $w.name; Suscripcion = $sn; ResourceGroup = $w.resourceGroup; Host = $h
                           Identidad = ""; Jobs = 0; Pipelines = 0; Warehouses = 0; Catalogos = 0; Estado = "" }
        Write-Host "`n  [$i/$($rows.Count)] $($w.name) ($h)" -ForegroundColor White
        if (-not $h) { $row.Estado = "SIN URL (workspace no desplegado)"; $summary.Add([pscustomobject]$row); continue }
        try {
            $filter = [uri]::EscapeDataString("applicationId eq `"$IdentityClientId`"")
            $found = Invoke-Dbx $h "GET" "/api/2.0/preview/scim/v2/ServicePrincipals?filter=$filter" $null
            $wanted = @("workspace-access", "databricks-sql-access")
            if ($found.totalResults -gt 0) {
                $spRes = @($found.Resources)[0]
                $have = @($spRes.entitlements | ForEach-Object { $_.value })
                $missing = @($wanted | Where-Object { $have -notcontains $_ })
                if (-not $missing) { $row.Identidad = "ya estaba"; Write-Ok "La identidad ya estaba dada de alta" }
                elseif ($WhatIf) { $row.Identidad = "ya estaba"; Write-Plan "Anadiria los permisos $($missing -join ', ')" }
                else {
                    $patch = @{ schemas = @("urn:ietf:params:scim:api:messages:2.0:PatchOp")
                                Operations = @(@{ op = "add"; path = "entitlements"; value = @($missing | ForEach-Object { @{ value = $_ } }) }) }
                    Invoke-Dbx $h "PATCH" "/api/2.0/preview/scim/v2/ServicePrincipals/$($spRes.id)" $patch | Out-Null
                    $row.Identidad = "ya estaba"; Write-Ok "La identidad ya estaba; anadidos los permisos $($missing -join ', ')"
                }
            }
            elseif ($WhatIf) { $row.Identidad = "se daria de alta"; Write-Plan "Daria de alta la identidad (workspace-access + databricks-sql-access, sin admin)" }
            else {
                $body = @{
                    schemas       = @("urn:ietf:params:scim:schemas:core:2.0:ServicePrincipal")
                    applicationId = $IdentityClientId
                    displayName   = $SpName
                    entitlements  = @($wanted | ForEach-Object { @{ value = $_ } })
                }
                Invoke-Dbx $h "POST" "/api/2.0/preview/scim/v2/ServicePrincipals" $body | Out-Null
                $row.Identidad = "dada de alta"; Write-Ok "Identidad dada de alta (workspace-access + databricks-sql-access, sin admin)"
            }
        }
        catch {
            $code = Get-HttpCode $_
            $detail = ""
            try { $detail = [string]$_.ErrorDetails.Message } catch { }
            if ($detail -match "Did not find workspace") { $row.Estado = "SIN INICIALIZAR: abrelo una vez desde el portal de Azure (Launch Workspace) y repite" }
            elseif ($code -eq 401 -or $code -eq 403) { $row.Estado = "SIN ACCESO: tu usuario no es Workspace Admin" }
            elseif ($code -eq 0) { $row.Estado = "SIN ACCESO: no se llega al workspace (red privada o DNS)" }
            else { $row.Estado = "ERROR HTTP $code" }
            Write-Warn2 "$($row.Estado). Se sigue con el siguiente."
            $summary.Add([pscustomobject]$row)
            continue
        }

        try {
            $pt = ""
            do {
                $q = "/api/2.1/jobs/list?limit=100"; if ($pt) { $q += "&page_token=$pt" }
                $r = Invoke-Dbx $h "GET" $q $null
                foreach ($j in @($r.jobs)) { if ($j -and (Grant-View $h "jobs" $j.job_id "job $($j.job_id)")) { $row.Jobs++ } }
                $pt = $r.next_page_token
            } while ($pt)
            $pt = ""
            do {
                $q = "/api/2.0/pipelines?max_results=100"; if ($pt) { $q += "&page_token=$pt" }
                $r = Invoke-Dbx $h "GET" $q $null
                foreach ($p in @($r.statuses)) { if ($p -and (Grant-View $h "pipelines" $p.pipeline_id "pipeline $($p.name)")) { $row.Pipelines++ } }
                $pt = $r.next_page_token
            } while ($pt)
            $r = Invoke-Dbx $h "GET" "/api/2.0/sql/warehouses" $null
            foreach ($s in @($r.warehouses)) { if ($s -and (Grant-View $h "warehouses" $s.id "warehouse $($s.name)")) { $row.Warehouses++ } }
            Write-Ok "CAN_VIEW: $($row.Jobs) jobs, $($row.Pipelines) pipelines, $($row.Warehouses) SQL warehouses"
        }
        catch { Write-Warn2 "CAN_VIEW incompleto: $($_.Exception.Message)" }

        if (-not $SkipUnityCatalog) {
            try {
                $cats = @(); $pt = ""
                do {
                    $q = "/api/2.1/unity-catalog/catalogs?max_results=100"; if ($pt) { $q += "&page_token=$pt" }
                    $r = Invoke-Dbx $h "GET" $q $null
                    $cats += @($r.catalogs); $pt = $r.next_page_token
                } while ($pt)
                foreach ($c in $cats) {
                    if (-not $c -or $SkipCatalogs -contains $c.name) { continue }
                    if ($WhatIf) { $row.Catalogos++; continue }
                    $chg = @{ changes = @(@{ principal = $IdentityClientId; add = @("BROWSE", "USE_CATALOG", "USE_SCHEMA") }) }
                    try {
                        Invoke-Dbx $h "PATCH" "/api/2.1/unity-catalog/permissions/catalog/$([uri]::EscapeDataString($c.name))" $chg | Out-Null
                        $row.Catalogos++
                    }
                    catch { Write-Warn2 "Catalogo $($c.name): $($_.Exception.Message) (hace falta ser owner del catalogo o metastore admin)" }
                }
                Write-Ok "Unity Catalog: BROWSE + USE_CATALOG + USE_SCHEMA en $($row.Catalogos) catalogos"
            }
            catch { Write-Warn2 "Unity Catalog no disponible en este workspace: $($_.Exception.Message)" }
        }
        $row.Estado = if ($WhatIf) { "WHATIF (sin cambios)" } else { "OK" }
        $summary.Add([pscustomobject]$row)
    }
}

# ---- Resumen --------------------------------------------------------------------------------
Write-Step "Resumen"
if ($summary.Count -gt 0) {
    $summary | Format-Table Workspace, Suscripcion, Identidad, Jobs, Pipelines, Warehouses, Catalogos, Estado -AutoSize -Wrap
    $summary | Export-Csv -Path "databricks-access-summary.csv" -NoTypeInformation -Encoding UTF8
    $ok = @($summary | Where-Object { $_.Estado -eq "OK" }).Count
    Write-Host "  $ok de $($summary.Count) workspaces con acceso completo. Detalle: databricks-access-summary.csv"
}
if ($failures.Count -gt 0) { Write-Warn2 "Fallos en roles de Azure: $($failures -join '; ')" }
Write-Host "`nNO hay que pegar nada en la herramienta: descubre sola los workspaces." -ForegroundColor Yellow
Write-Host "Los permisos tardan 5-10 minutos en propagarse. Despues, en el chat: /agent databricks-dependency-live -> 'Lista los workspaces de Databricks'." -ForegroundColor Yellow
