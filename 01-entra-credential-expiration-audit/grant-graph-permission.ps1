# grant-graph-permission.ps1
# Microsoft Entra credential expiration audit · Azure SRE Agent
# Grants the Microsoft Graph application permission Application.Read.All
# to the user-assigned managed identity of your Azure SRE Agent.
#
# - Run it in PowerShell with an account that holds the Privileged Role Administrator role.
# - It is idempotent: if the permission is already assigned, no duplicate assignment is created.
# - It only grants read access. Do not grant Microsoft Graph write permissions to the tool.
#
# Version 1.1 · October 2026

# ---------------------------------------------------------------------------
# REQUIRED CONFIGURATION
# Replace the value with the Client ID of the user-assigned managed identity
# of YOUR Azure SRE Agent (Step 0 of the guide). A Client ID is not a secret.
# ---------------------------------------------------------------------------
$managedIdentityClientId = "<YOUR_AGENT_CLIENT_ID>"

if ($managedIdentityClientId -like "<*") {
    throw "Replace <YOUR_AGENT_CLIENT_ID> with the Client ID of your agent's managed identity before you run this script."
}

Install-Module Microsoft.Graph -Scope CurrentUser -Force
Import-Module Microsoft.Graph.Applications

Connect-MgGraph -Scopes "Application.Read.All", "AppRoleAssignment.ReadWrite.All"

# Microsoft Graph App ID (identical in every tenant).
$graphAppId = "00000003-0000-0000-c000-000000000000"

$managedIdentitySp = Get-MgServicePrincipal -Filter "appId eq '$managedIdentityClientId'"
$graphSp = Get-MgServicePrincipal -Filter "appId eq '$graphAppId'"

if (-not $managedIdentitySp) {
    throw "Managed identity service principal not found. Verify the Client ID."
}

$appRole = $graphSp.AppRoles | Where-Object {
    $_.Value -eq "Application.Read.All" -and
    $_.AllowedMemberTypes -contains "Application"
}

if (-not $appRole) {
    throw "Microsoft Graph Application.Read.All app role was not found."
}

$existingAssignment = Get-MgServicePrincipalAppRoleAssignment `
    -ServicePrincipalId $managedIdentitySp.Id -All | Where-Object {
        $_.ResourceId -eq $graphSp.Id -and $_.AppRoleId -eq $appRole.Id
    }

if (-not $existingAssignment) {
    $params = @{
        principalId = $managedIdentitySp.Id
        resourceId  = $graphSp.Id
        appRoleId   = $appRole.Id
    }

    New-MgServicePrincipalAppRoleAssignment `
        -ServicePrincipalId $managedIdentitySp.Id `
        -BodyParameter $params

    Write-Host "Application.Read.All granted to the managed identity." -ForegroundColor Green
}
else {
    Write-Host "Application.Read.All is already assigned." -ForegroundColor Yellow
}

Disconnect-MgGraph
