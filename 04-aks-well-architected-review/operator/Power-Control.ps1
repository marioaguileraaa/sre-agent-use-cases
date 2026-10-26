param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Start', 'Stop')]
    [string]$Action
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ApprovedSubscriptionId = '<APPROVED_LAB_SUBSCRIPTION_ID>'
$ApprovedTenantId = '<APPROVED_TENANT_ID>'
$ApprovedSchedulerPrincipalId = '<NEW_AUTOMATION_PRINCIPAL_ID>'
$ClusterId = "/subscriptions/$ApprovedSubscriptionId/resourceGroups/rg-aks-sre-demo-small/providers/Microsoft.ContainerService/managedClusters/aks-sre-demo-small"
$ApiVersion = '2025-05-01'
$TokenCache = $null

function Assert-PowerConfiguration {
    foreach ($value in @($ApprovedSubscriptionId, $ApprovedTenantId, $ApprovedSchedulerPrincipalId)) {
        $parsed = [guid]::Empty
        if (-not [guid]::TryParseExact($value, 'D', [ref]$parsed) -or $parsed -eq [guid]::Empty) {
            throw 'configuration_required: configure the fixed subscription, tenant and NEW Automation principal before authentication.'
        }
    }
}

function Get-PowerToken {
    if ($null -ne $script:TokenCache -and $script:TokenCache.expires -gt [DateTimeOffset]::UtcNow.AddMinutes(5)) {
        return $script:TokenCache.value
    }
    if (-not $env:IDENTITY_ENDPOINT -or -not $env:IDENTITY_HEADER) {
        throw 'managed_identity_unavailable: only the Automation account identity is allowed; no CLI, cached user or credential fallback.'
    }
    $endpoint = [uri]$env:IDENTITY_ENDPOINT
    if (-not $endpoint.IsLoopback -or $endpoint.Scheme -notin @('http', 'https') -or $endpoint.UserInfo -or $endpoint.Fragment) {
        throw 'unsafe_identity_endpoint: expected the Automation sandbox loopback identity endpoint.'
    }
    $separator = if ($endpoint.Query) { '&' } else { '?' }
    $uri = $endpoint.AbsoluteUri + $separator + 'resource=' + [uri]::EscapeDataString('https://management.azure.com/')
    $response = Invoke-RestMethod -Method Get -Uri $uri -TimeoutSec 30 -MaximumRedirection 0 -Headers @{
        'X-IDENTITY-HEADER' = $env:IDENTITY_HEADER
        Metadata = 'True'
    }
    $parts = ([string]$response.access_token).Split('.')
    if ($parts.Count -ne 3) { throw 'invalid_identity_token: expected a service-issued JWT; token is never printed.' }
    $payload = $parts[1].Replace('-', '+').Replace('_', '/')
    $payload = $payload.PadRight($payload.Length + ((4 - $payload.Length % 4) % 4), '=')
    $claims = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) | ConvertFrom-Json
    if ($claims.tid -ne $ApprovedTenantId -or $claims.oid -ne $ApprovedSchedulerPrincipalId -or
        ([string]$claims.aud).TrimEnd('/') -ne 'https://management.azure.com') {
        throw 'identity_mismatch: tenant/principal/audience differs from the fixed NEW scheduler identity.'
    }
    $script:TokenCache = @{
        value = [string]$response.access_token
        expires = [DateTimeOffset]::FromUnixTimeSeconds([long]$claims.exp)
    }
    return $script:TokenCache.value
}

function Invoke-ClusterPowerRequest {
    param([ValidateSet('GET', 'POST')][string]$Method, [string]$Suffix = '')
    if (($Method -eq 'GET' -and $Suffix -ne '') -or
        ($Method -eq 'POST' -and $Suffix -notin @('/start', '/stop'))) {
        throw 'unsafe_operation: only the exact cluster GET and start/stop POST are allowed.'
    }
    $arguments = @{
        Method = $Method
        Uri = "https://management.azure.com$ClusterId$Suffix`?api-version=$ApiVersion"
        TimeoutSec = 30
        MaximumRedirection = 0
        Headers = @{Authorization = 'Bearer ' + (Get-PowerToken)}
    }
    if ($Method -eq 'POST') { $arguments.ContentType = 'application/json'; $arguments.Body = '{}' }
    try {
        return Invoke-RestMethod @arguments
    } catch [Microsoft.PowerShell.Commands.HttpResponseException] {
        $status = [int]$_.Exception.Response.StatusCode
        throw "arm_operation_failed: exact demo cluster $Method failed with HTTP $status; no alternate target or identity."
    }
}

function Assert-ClusterPowerScope {
    param($Cluster)
    if ($Cluster.id -ne $ClusterId) { throw 'scope_mismatch: ARM returned a different cluster.' }
    if ($Cluster.properties.nodeProvisioningProfile -and $Cluster.properties.nodeProvisioningProfile.mode -eq 'Auto') {
        throw 'unsupported_stop_start: NAP clusters are excluded.'
    }
    $pools = @($Cluster.properties.agentPoolProfiles)
    if ($pools.Count -eq 0 -or @($pools | Where-Object { $_.type -ne 'VirtualMachineScaleSets' }).Count -gt 0) {
        throw 'unsupported_stop_start: only observed VMSS-backed node pools are allowed.'
    }
}

function Invoke-DemoPower {
    Assert-PowerConfiguration
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $wanted = if ($Action -eq 'Start') { 'Running' } else { 'Stopped' }
    $cluster = Invoke-ClusterPowerRequest -Method GET
    Assert-ClusterPowerScope $cluster
    while ($cluster.properties.provisioningState -ne 'Succeeded') {
        if ($cluster.properties.provisioningState -in @('Failed', 'Canceled') -or $clock.Elapsed.TotalSeconds -ge 3600) {
            throw 'cluster_not_ready: failed/busy provisioning was not changed; inspect the failed job and current costs.'
        }
        Start-Sleep -Seconds 30
        $cluster = Invoke-ClusterPowerRequest -Method GET
        Assert-ClusterPowerScope $cluster
    }
    $before = [string]$cluster.properties.powerState.code
    $posted = $false
    if ($before -ne $wanted) {
        Invoke-ClusterPowerRequest -Method POST -Suffix ('/' + $Action.ToLowerInvariant()) | Out-Null
        $posted = $true
        do {
            if ($clock.Elapsed.TotalSeconds -ge 3600) {
                throw 'power_transition_timeout: ARM acceptance is not completed stop/start; no success receipt is returned.'
            }
            Start-Sleep -Seconds 30
            $cluster = Invoke-ClusterPowerRequest -Method GET
            Assert-ClusterPowerScope $cluster
        } while ($cluster.properties.powerState.code -ne $wanted -or $cluster.properties.provisioningState -ne 'Succeeded')
    }
    [pscustomobject]@{
        status = 'completed'
        cluster_id = $ClusterId
        scheduler_principal_id = $ApprovedSchedulerPrincipalId
        action = $Action
        requested_transition = $posted
        before_power_state = $before
        observed_power_state = [string]$cluster.properties.powerState.code
        observed_provisioning_state = [string]$cluster.properties.provisioningState
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        duration_seconds = [math]::Round($clock.Elapsed.TotalSeconds, 2)
    } | ConvertTo-Json -Compress
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        Invoke-DemoPower
    } finally {
        $script:TokenCache = $null
    }
}
