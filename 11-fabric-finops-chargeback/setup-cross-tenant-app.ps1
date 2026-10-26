<#
.SYNOPSIS
    OPTION B (cross-tenant) only - step 1 of 2. Run in the tenant of the Azure SRE Agent (tenant A).
    Creates a multi-tenant app with NO secrets and NO certificates and a Federated Identity Credential (FIC)
    that trusts the SRE Agent user-assigned managed identity. The tool exchanges the managed identity token
    for a token of this app in the Fabric tenant (tenant B).

.DESCRIPTION
    Idempotent: reuses the app and the FIC if they already exist. One app serves any number of customer tenants.
    Do NOT add Power BI / Fabric API permissions with admin consent to this app: the Fabric admin APIs reject
    service principals that hold them. The default (no permissions) is what you want.

.NOTES
    Permission to register applications in tenant A (Application Developer or higher). Azure CLI 2.60+.

.EXAMPLE
    ./setup-cross-tenant-app.ps1 -SreTenantId <SRE_TENANT_ID> -UamiPrincipalId <UAMI_PRINCIPAL_ID>
    # then, in the Fabric tenant:
    ./grant-fabric-finops-access.ps1 -FabricTenantId <TARGET_FABRIC_TENANT_ID> -SubscriptionId <SUB_ID> -AppClientId <printed appId>
#>
param(
    [Parameter(Mandatory = $true)] [string] $SreTenantId,
    [Parameter(Mandatory = $true)] [string] $UamiPrincipalId,
    [string] $AppName = "sre-agent-fabric-cross-tenant-bridge",
    [string] $FicName = "sre-agent-uami-fic",
    [switch] $SkipLogin
)
$ErrorActionPreference = "Stop"

if (-not $SkipLogin) { az login --tenant $SreTenantId --allow-no-subscriptions | Out-Null }
if ((az account show --query tenantId -o tsv) -ne $SreTenantId) { throw "Signed in to the wrong tenant. Run: az login --tenant $SreTenantId" }

# 1. Multi-tenant app (no secrets, no certificates)
$appId = az ad app list --display-name $AppName --query "[0].appId" -o tsv
if (-not $appId) {
    $appId = az ad app create --display-name $AppName --sign-in-audience AzureADMultipleOrgs --query appId -o tsv
    Write-Host "[OK] App created: $appId" -ForegroundColor Green
} else {
    az ad app update --id $appId --sign-in-audience AzureADMultipleOrgs | Out-Null
    Write-Host "[OK] App reused: $appId" -ForegroundColor Green
}
if (-not (az ad sp show --id $appId --query id -o tsv 2>$null)) { az ad sp create --id $appId | Out-Null }
$appObjId = az ad app show --id $appId --query id -o tsv

# 2. Federated Identity Credential that trusts the SRE Agent managed identity
$issuer   = "https://login.microsoftonline.com/$SreTenantId/v2.0"
$existing = az ad app federated-credential list --id $appObjId --query "[?subject=='$UamiPrincipalId' && issuer=='$issuer'].name" -o tsv
if ($existing) {
    Write-Host "[OK] FIC already present: $existing" -ForegroundColor Green
} else {
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("fic-" + [guid]::NewGuid().ToString("N") + ".json")
    $fic = @{ name = $FicName; issuer = $issuer; subject = $UamiPrincipalId; audiences = @("api://AzureADTokenExchange"); description = "Trust the Azure SRE Agent managed identity" }
    [IO.File]::WriteAllText($tmp, ($fic | ConvertTo-Json -Depth 4), (New-Object Text.UTF8Encoding($false)))
    az ad app federated-credential create --id $appObjId --parameters "@$tmp" | Out-Null
    Remove-Item $tmp -ErrorAction SilentlyContinue
    Write-Host "[OK] FIC created (issuer $issuer, subject $UamiPrincipalId)" -ForegroundColor Green
}

Write-Host ""
Write-Host "FEDERATED_APP_CLIENT_ID = $appId" -ForegroundColor Cyan
Write-Host "Give this value to the Fabric administrator of the customer tenant. Next step (run in tenant B):"
Write-Host "  ./grant-fabric-finops-access.ps1 -FabricTenantId <TARGET_FABRIC_TENANT_ID> -SubscriptionId <SUB_ID> -AppClientId $appId"
