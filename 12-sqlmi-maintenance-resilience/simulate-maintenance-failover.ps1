<#
.SYNOPSIS
  Controlled maintenance drill: triggers a manual failover of a PRE-PRODUCTION SQL Managed Instance
  to check whether applications retry or surface errors to users.

.DESCRIPTION
  A manual failover reproduces what happens during a maintenance reconfiguration: open connections
  drop for a few seconds (errors 40613, 40197, 4060, 233...).
  - Use it ONLY in pre-production, and warn the application teams first.
  - Azure allows 1 manual failover every 15 minutes per instance.
  - After the drill, ask the SRE Agent: "Generate the report with period=last_7d"
    and review the applications table: any app that is not "Resiliente" needs retry logic.
  Requires SQL Managed Instance Contributor (or Contributor) on the instance.

.EXAMPLE
  ./simulate-maintenance-failover.ps1 -SubscriptionId "<SUB_ID>" -ResourceGroup "rg-sql-pre" -InstanceName "sqlmi-core-pre"
#>
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = "High")]
param(
  [Parameter(Mandatory)] [string] $SubscriptionId,
  [Parameter(Mandatory)] [string] $ResourceGroup,
  [Parameter(Mandatory)] [string] $InstanceName,
  [ValidateSet("Primary", "ReadableSecondary")] [string] $ReplicaType = "Primary"
)
$ErrorActionPreference = "Stop"

if ($InstanceName -match "(?i)(prd|prod|pro)(\b|-|$)") {
  throw "The name '$InstanceName' looks like production. This drill is for pre-production only."
}
$mi = & az sql mi show -g $ResourceGroup -n $InstanceName --subscription $SubscriptionId -o json 2>&1
if ($LASTEXITCODE -ne 0) { throw "Instance not found: $mi" }
$mi = $mi | ConvertFrom-Json
Write-Host "Instance: $($mi.name)  ($($mi.location), $($mi.skuName), connection $($mi.proxyOverride))" -ForegroundColor Cyan

if ($PSCmdlet.ShouldProcess($InstanceName, "Manual failover ($ReplicaType)")) {
  $start = Get-Date
  Write-Host "Failover started at $($start.ToString('HH:mm:ss')). Watch the applications now..." -ForegroundColor Yellow
  & az sql mi failover -g $ResourceGroup -n $InstanceName --subscription $SubscriptionId --replica-type $ReplicaType
  if ($LASTEXITCODE -ne 0) { throw "Failover failed (remember: at most 1 every 15 minutes)." }
  $secs = [int]((Get-Date) - $start).TotalSeconds
  Write-Host "Failover completed in $secs s." -ForegroundColor Green
  Write-Host "Next step: wait 5-10 minutes for Application Insights data, then ask the SRE Agent for the report with period=last_7d."
}
