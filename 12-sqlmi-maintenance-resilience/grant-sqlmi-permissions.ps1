<#
.SYNOPSIS
  Grants the Azure SRE Agent managed identity the READ-ONLY permissions that the
  generate-sqlmi-maintenance-report tool needs, and writes the tool configuration file.

.DESCRIPTION
  For every subscription that hosts SQL Managed Instances:
    - Reader               (MI inventory, windows, failover groups, Resource Graph, Service Health)
    - Monitoring Reader    (CPU metrics, Resource Health, Activity Log, alert rules)
  For every Log Analytics workspace where the applications' Application Insights write:
    - Log Analytics Reader (AppDependencies and AppRequests to measure user impact)

  None of these roles can change resources. Idempotent: existing assignments are skipped.
  At the end it writes sqlmi-tool-config.txt with the values for the tool (guide, step 4).

.EXAMPLE
  ./grant-sqlmi-permissions.ps1 -AgentIdentityName "<SRE_AGENT_UAMI_NAME>" -AgentIdentityResourceGroup "<UAMI_RG>" `
      -SubscriptionIds "<SUB_ID_1>","<SUB_ID_2>" `
      -WorkspaceResourceIds "/subscriptions/<SUB>/resourceGroups/<RG>/providers/Microsoft.OperationalInsights/workspaces/<WS>"
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)] [string] $AgentIdentityName,
  [Parameter(Mandatory)] [string] $AgentIdentityResourceGroup,
  [Parameter(Mandatory)] [string[]] $SubscriptionIds,
  [string[]] $WorkspaceResourceIds = @(),
  [string] $IdentitySubscriptionId = "",
  [string] $OutputFile = "sqlmi-tool-config.txt"
)
$ErrorActionPreference = "Stop"

function Invoke-Az {
  param([string[]] $Arguments)
  $out = & az @Arguments 2>&1
  if ($LASTEXITCODE -ne 0) { throw "az $($Arguments -join ' ') failed:`n$out" }
  return $out
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw "Install Azure CLI and run 'az login'." }
$idSub = if ($IdentitySubscriptionId) { $IdentitySubscriptionId } else { $SubscriptionIds[0] }

Write-Host "1) SRE Agent managed identity: $AgentIdentityName" -ForegroundColor Cyan
$identity = Invoke-Az @("identity", "show", "-n", $AgentIdentityName, "-g", $AgentIdentityResourceGroup,
                        "--subscription", $idSub, "-o", "json") | ConvertFrom-Json
$principalId = $identity.principalId
$clientId = $identity.clientId
Write-Host "   clientId    = $clientId"
Write-Host "   principalId = $principalId"

function Grant-Role([string] $Role, [string] $Scope) {
  $existing = Invoke-Az @("role", "assignment", "list", "--assignee-object-id", $principalId, "--role", $Role,
                          "--scope", $Scope, "--query", "length(@)", "-o", "tsv")
  if ([int]$existing -gt 0) { Write-Host "   = $Role already assigned on $Scope"; return }
  Invoke-Az @("role", "assignment", "create", "--assignee-object-id", $principalId,
              "--assignee-principal-type", "ServicePrincipal", "--role", $Role, "--scope", $Scope, "-o", "none") | Out-Null
  Write-Host "   + $Role on $Scope" -ForegroundColor Green
}

Write-Host "2) Subscription roles (Reader + Monitoring Reader)" -ForegroundColor Cyan
foreach ($sub in $SubscriptionIds) {
  Grant-Role "Reader" "/subscriptions/$sub"
  Grant-Role "Monitoring Reader" "/subscriptions/$sub"
}

$workspaceIds = @()
Write-Host "3) Log Analytics workspace roles (Log Analytics Reader)" -ForegroundColor Cyan
if (-not $WorkspaceResourceIds) {
  Write-Warning "Without -WorkspaceResourceIds the tool cannot measure user impact per application."
}
foreach ($ws in $WorkspaceResourceIds) {
  Grant-Role "Log Analytics Reader" $ws
  $wsSub = ($ws -split "/")[2]
  $customerId = Invoke-Az @("resource", "show", "--ids", $ws, "--subscription", $wsSub,
                            "--query", "properties.customerId", "-o", "tsv")
  $workspaceIds += $customerId.Trim()
}

Write-Host "4) Tool configuration file: $OutputFile" -ForegroundColor Cyan
@(
  "# Values for generate-sqlmi-maintenance-report (CONFIGURE block)",
  "MANAGED_IDENTITY_CLIENT_ID = `"$clientId`"",
  "SUBSCRIPTION_IDS = `"$($SubscriptionIds -join ',')`"",
  "LOG_ANALYTICS_WORKSPACE_IDS = `"$($workspaceIds -join ',')`""
) | Set-Content -Path $OutputFile -Encoding utf8
Get-Content $OutputFile | ForEach-Object { Write-Host "   $_" }
Write-Host "`nDone. Role assignments can take up to 10 minutes to propagate." -ForegroundColor Green
