<#
.SYNOPSIS
  Grants the SRE Agent identity the READ-ONLY roles of the AKS Well-Architected Review case
  on one, several or all subscriptions (or a Management Group) and generates the
  APPROVED_CLUSTERS block ready to paste into generate-aks-waf-report.py.

.DESCRIPTION
  Roles (all read-only; cluster admin credentials are never used):
    - Reader                                          -> scope (MG or each subscription)
    - Cost Management Reader (optional, -IncludeCost) -> scope
    - Azure Kubernetes Service Cluster User Role      -> each AKS cluster (or the scope with -AksRolesAtScope)
    - Azure Kubernetes Service RBAC Reader            -> each AKS cluster (or the scope with -AksRolesAtScope)

  Scope modes (choose one; with none, the active subscription of "az login" is used):
    -ManagementGroupId <mg>     Assigns the roles ONCE on the Management Group (all its subscriptions
                                inherit them, including future ones) and goes through its subscriptions.
    -AllSubscriptions           Every enabled subscription of the tenant that your "az login" can see.
    -SubscriptionIds a,b,c      Explicit list of subscriptions.
    -SubscriptionId <id>        A single subscription (kept for compatibility with the previous version).

  Output:
    - Table with the authentication mode of each AKS cluster (Entra ID + Azure RBAC is required to
      read workloads) and the CSV file aks-auth-modes.csv.
    - File approved-clusters.generated.py with CLUSTER_DEFAULTS + APPROVED_CLUSTERS
      (one line per cluster, with its subscription_id). Paste it over the same variables at the
      top of your private copy of generate-aks-waf-report.py.

  Who can run it: Owner, User Access Administrator or Role Based Access Control Administrator
  on the chosen scope, with Azure CLI signed in ("az login") to the right tenant.
  Running it again is safe: existing assignments are not duplicated.

.EXAMPLE
  # Recommended for many subscriptions: one Management Group, AKS roles at scope level
  .\grant-aks-permissions.ps1 -IdentityClientId "<client-id>" -ManagementGroupId "mg-platform" -AksRolesAtScope -IncludeCost

.EXAMPLE
  # Every subscription your session can see
  .\grant-aks-permissions.ps1 -IdentityClientId "<client-id>" -AllSubscriptions -AksRolesAtScope

.EXAMPLE
  # Explicit list of subscriptions, AKS roles cluster by cluster (least privilege)
  .\grant-aks-permissions.ps1 -IdentityClientId "<client-id>" -SubscriptionIds "<sub-1>","<sub-2>"

.EXAMPLE
  # Only some clusters: "subscription/resourceGroup/name" (or "resourceGroup/name" with a single subscription)
  .\grant-aks-permissions.ps1 -IdentityClientId "<client-id>" -Clusters "<sub-1>/rg-aks-prod/aks-prod-01","<sub-2>/rg-aks/aks-pre-01"
#>
param(
    [Parameter(Mandatory)][string]$IdentityClientId,
    [string]$ManagementGroupId,
    [switch]$AllSubscriptions,
    [string[]]$SubscriptionIds,
    [string]$SubscriptionId,
    [string[]]$Clusters,
    [switch]$IncludeCost,
    [switch]$AksRolesAtScope,
    [ValidateSet("UNSPECIFIED", "PRODUCTION", "LAB")][string]$Environment = "UNSPECIFIED",
    [string]$OutFile = "approved-clusters.generated.py"
)
$ErrorActionPreference = "Stop"

$ROLE_READER          = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
$ROLE_AKS_CLUSTERUSER = "4abbcc35-e782-43d8-92c5-2d3f1bd2253f"
$ROLE_AKS_RBACREADER  = "7f6c6a51-bcf8-42ba-9220-52d62157d7db"
$ROLE_COST_READER     = "72fafb9e-0641-4937-9268-a91bfd8191a3"
$MAX_CLUSTERS         = 500
$failures = New-Object System.Collections.Generic.List[string]

function Grant([string]$principalId, [string]$roleId, [string]$roleName, [string]$scope) {
    # Windows PowerShell 5.1 turns redirected az stderr into a terminating error under "Stop"; the exit code is checked instead.
    $ErrorActionPreference = "Continue"
    $null = az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal `
        --role $roleId --scope $scope --only-show-errors -o none 2>&1
    if ($LASTEXITCODE -ne 0) {
        $failures.Add("$roleName -> $scope")
        Write-Host "  [ERROR] $roleName  ->  $scope (check your permissions on that scope)" -ForegroundColor Red
    } else {
        Write-Host "  [OK] $roleName  ->  $scope" -ForegroundColor Green
    }
}

function Get-MgSubscriptions([string]$mg) {
    $url = "https://management.azure.com/providers/Microsoft.Management/managementGroups/$mg/descendants?api-version=2020-05-01"
    $subs = @()
    while ($url) {
        # On Windows az is a batch file: quote the URL so cmd.exe does not cut a nextLink at "&".
        $urlArg = if ($env:OS -eq "Windows_NT") { "`"$url`"" } else { $url }
        $page = az rest --method get --url $urlArg -o json | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { throw "Could not read Management Group '$mg'. Check the name (the ID, not the display name) and your permissions." }
        $subs += @($page.value | Where-Object { $_.type -eq "Microsoft.Management/managementGroups/subscriptions" -or $_.type -eq "/subscriptions" } | ForEach-Object { $_.name })
        $url = $page.nextLink
    }
    return $subs
}

Write-Host "`n== 1. Tenant, identity and subscriptions ==" -ForegroundColor Cyan
$tenantId = az account show --query tenantId -o tsv
if (-not $tenantId) { throw "No Azure CLI session found. Run az login first." }
$principalId = & { $ErrorActionPreference = "Continue"; az ad sp show --id $IdentityClientId --query id -o tsv 2>$null }
if (-not $principalId) { throw "No identity with Client ID $IdentityClientId was found in this tenant." }
Write-Host "  Tenant: $tenantId"
Write-Host "  SRE Agent identity: clientId=$IdentityClientId  principalId=$principalId"

$explicitClusters = @{}
if ($Clusters) {
    foreach ($c in $Clusters) {
        $p = $c.Split("/")
        if ($p.Count -eq 3) { $sub = $p[0].ToLower(); $rg = $p[1]; $name = $p[2] }
        elseif ($p.Count -eq 2) {
            $sub = if ($SubscriptionId) { $SubscriptionId } else { az account show --query id -o tsv }
            $sub = $sub.ToLower(); $rg = $p[0]; $name = $p[1]
        } else { throw "Invalid format '$c'. Use  subscription/resourceGroup/name  or  resourceGroup/name" }
        if (-not $explicitClusters.ContainsKey($sub)) { $explicitClusters[$sub] = @() }
        $explicitClusters[$sub] += "$rg/$name".ToLower()
    }
}

$scopes = @()
if ($ManagementGroupId) {
    $scopes = @("/providers/Microsoft.Management/managementGroups/$ManagementGroupId")
    $subs = @(Get-MgSubscriptions $ManagementGroupId)
} elseif ($AllSubscriptions) {
    $subs = @(az account list --all --query "[?tenantId=='$tenantId' && state=='Enabled'].id" -o tsv)
} elseif ($SubscriptionIds) {
    $subs = @($SubscriptionIds | ForEach-Object { $_.Split(",") } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
} elseif ($explicitClusters.Count -gt 0) {
    $subs = @($explicitClusters.Keys)
} elseif ($SubscriptionId) {
    $subs = @($SubscriptionId)
} else {
    $subs = @(az account show --query id -o tsv)
}
$subs = @($subs | ForEach-Object { $_.ToLower() } | Select-Object -Unique)
if (-not $subs) { throw "No subscription was found in the given scope." }
if (-not $scopes) { $scopes = @($subs | ForEach-Object { "/subscriptions/$_" }) }
Write-Host "  Subscriptions in scope: $($subs.Count)"

Write-Host "`n== 2. Read roles on the scope ==" -ForegroundColor Cyan
foreach ($scope in $scopes) {
    Grant $principalId $ROLE_READER "Reader" $scope
    if ($IncludeCost) { Grant $principalId $ROLE_COST_READER "Cost Management Reader" $scope }
    if ($AksRolesAtScope) {
        Grant $principalId $ROLE_AKS_CLUSTERUSER "Azure Kubernetes Service Cluster User Role" $scope
        Grant $principalId $ROLE_AKS_RBACREADER  "Azure Kubernetes Service RBAC Reader" $scope
    }
}

Write-Host "`n== 3. AKS clusters per subscription ==" -ForegroundColor Cyan
$found = @()
foreach ($sub in $subs) {
    $json = & { $ErrorActionPreference = "Continue"; az aks list --subscription $sub --query "[].{name:name, rg:resourceGroup, id:id, managed:aadProfile.managed, azRbac:aadProfile.enableAzureRbac}" -o json 2>$null }
    if ($LASTEXITCODE -ne 0) { $failures.Add("az aks list -> $sub"); Write-Host "  [ERROR] Could not list the AKS clusters of $sub" -ForegroundColor Red; continue }
    # ForEach-Object unrolls the array: Windows PowerShell 5.1 ConvertFrom-Json returns it as a single object.
    $list = @($json | ConvertFrom-Json | ForEach-Object { $_ })
    if ($explicitClusters.Count -gt 0) {
        $wanted = $explicitClusters[$sub]
        $list = @($list | Where-Object { $wanted -and $wanted -contains "$($_.rg)/$($_.name)".ToLower() })
    }
    Write-Host "  $sub : $($list.Count) AKS cluster(s)"
    foreach ($aks in $list) {
        $found += [pscustomobject]@{ Subscription = $sub; ResourceGroup = $aks.rg; Name = $aks.name; Id = $aks.id
                                     Managed = [bool]$aks.managed; AzureRbac = [bool]$aks.azRbac }
    }
}
if (-not $found) { throw "No AKS cluster was found in the given scope." }
if ($found.Count -gt $MAX_CLUSTERS) { throw "Found $($found.Count) AKS clusters; the tool accepts up to $MAX_CLUSTERS. Use -SubscriptionIds or -Clusters to narrow the scope." }

if (-not $AksRolesAtScope) {
    Write-Host "`n== 4. AKS roles on each cluster ==" -ForegroundColor Cyan
    foreach ($aks in $found) {
        Write-Host " $($aks.Name)"
        Grant $principalId $ROLE_AKS_CLUSTERUSER "Azure Kubernetes Service Cluster User Role" $aks.Id
        Grant $principalId $ROLE_AKS_RBACREADER  "Azure Kubernetes Service RBAC Reader" $aks.Id
    }
} else {
    Write-Host "`n== 4. AKS roles already assigned at scope level (this also covers future clusters) ==" -ForegroundColor Cyan
}

Write-Host "`n== 5. Authentication mode of the clusters ==" -ForegroundColor Cyan
$summary = foreach ($aks in $found) {
    $mode = if ($aks.Managed -and $aks.AzureRbac) { "OK: Entra ID + Azure RBAC" }
            elseif ($aks.Managed) { "WARNING: Entra ID with Kubernetes RBAC -> workloads 'No evaluado'" }
            else { "WARNING: no Entra ID -> ARM part only; workloads 'No evaluado'" }
    [pscustomobject]@{ Subscription = $aks.Subscription; ResourceGroup = $aks.ResourceGroup; Cluster = $aks.Name; KubernetesRead = $mode }
}
$summary | Format-Table -AutoSize -Wrap
$summary | Export-Csv -Path "aks-auth-modes.csv" -NoTypeInformation -Encoding UTF8
$okCount = @($summary | Where-Object { $_.KubernetesRead -like "OK*" }).Count
Write-Host "  $okCount of $(@($summary).Count) clusters with full Kubernetes read access. Details: aks-auth-modes.csv"

Write-Host "`n== 6. Configuration block -> $OutFile ==" -ForegroundColor Cyan
$defaultSub = ($found | Group-Object Subscription | Sort-Object Count -Descending | Select-Object -First 1).Name
$dupes = @($found | Group-Object Name | Where-Object { $_.Count -gt 1 } | ForEach-Object { $_.Name })
$costScope = if ($IncludeCost) { "node_resource_group" } else { "disabled" }
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Generated by grant-aks-permissions.ps1 on $(Get-Date -Format 'yyyy-MM-dd HH:mm'): $($found.Count) AKS clusters in $(@($found | Select-Object -ExpandProperty Subscription -Unique).Count) subscriptions.")
$lines.Add("# Replace these 5 variables at the top of your private copy of generate-aks-waf-report.py.")
$lines.Add("SUBSCRIPTION_ID = `"$defaultSub`"")
$lines.Add("TENANT_ID = `"$tenantId`"")
$lines.Add("MANAGED_IDENTITY_CLIENT_ID = `"$IdentityClientId`"")
$lines.Add("CLUSTER_DEFAULTS = {")
$lines.Add("    `"environment`": `"$Environment`",")
$lines.Add("    `"kubernetes_enabled`": True,")
$lines.Add("    `"include_node_resource_group`": True,")
$lines.Add("    `"advisor_enabled`": True,")
$lines.Add("    `"approved_related_resource_ids`": [],")
$lines.Add("    `"approved_cost_resource_ids`": [],")
$lines.Add("    `"cost_scope`": `"$costScope`",")
$lines.Add("    `"cost_timeframe`": `"month_to_date`",")
$lines.Add("    `"requirements`": {},")
$lines.Add("}")
$lines.Add("APPROVED_CLUSTERS = {")
foreach ($aks in ($found | Sort-Object Subscription, Name)) {
    $key = $aks.Name
    $extra = ""
    if ($dupes -contains $aks.Name) {
        $key = ($aks.Subscription.Substring(0, 8) + "-" + $aks.Name)
        if ($key.Length -gt 63) { $key = $key.Substring(0, 63) }
        $extra = ", `"aks_name`": `"$($aks.Name)`""
    }
    $lines.Add("    `"$key`": {`"resource_group`": `"$($aks.ResourceGroup)`", `"subscription_id`": `"$($aks.Subscription)`"$extra},")
}
$lines.Add("}")
[IO.File]::WriteAllText($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutFile), ($lines -join "`n") + "`n", (New-Object Text.UTF8Encoding $false))
$lines | Select-Object -First 25 | ForEach-Object { Write-Host $_ }
if ($lines.Count -gt 25) { Write-Host "    ... ($($found.Count) clusters in total, see $OutFile)" }
if ($dupes) { Write-Host "  Names used in more than one subscription (key prefixed with the subscription, plus aks_name): $($dupes -join ', ')" -ForegroundColor Yellow }

Write-Host "`nIMPORTANT: in the portal tool, keep the cluster_name parameter as free text (NO enum)." -ForegroundColor Yellow
Write-Host "Role assignments can take 5-10 minutes to propagate." -ForegroundColor Yellow
if ($failures.Count -gt 0) {
    Write-Host "`n$($failures.Count) operation(s) failed:" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
