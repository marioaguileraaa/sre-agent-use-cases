param(
    [ValidateSet('Preflight', 'Deploy', 'Readback')]
    [string]$Mode = 'Preflight',
    [string]$SettingsPath = (Join-Path $PSScriptRoot 'settings.example.json'),
    [switch]$ApproveSpend,
    [switch]$ApproveSchedulerRole,
    [switch]$ApproveAuditRoles,
    [switch]$ApproveDemoRole
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ApprovedSubscriptionId = '<APPROVED_LAB_SUBSCRIPTION_ID>'
$ApprovedTenantId = '<APPROVED_TENANT_ID>'
$ResourceGroup = 'rg-aks-sre-demo-small'
$ClusterName = 'aks-sre-demo-small'
$AutomationName = 'aa-aks-sre-demo-small'
$RunbookName = 'Control-DemoAksPower'
$AutomationApi = '2023-11-01'
$AssetRoot = $PSScriptRoot

function Assert-OperatorConfiguration {
    param([hashtable]$Config)
    $keys = @('subscription_id', 'tenant_id', 'kubernetes_version', 'node_vm_size', 'approved_thirty_day_budget_eur',
              'approval_reference', 'audit_principal_id', 'grant_audit_read_roles', 'demo_operator_principal_id', 'grant_demo_operator_role')
    if ($Config.Count -ne $keys.Count -or @($Config.Keys | Where-Object { $_ -notin $keys }).Count) {
        throw 'configuration_required: use every declared settings field and no arbitrary scope/URL/command overrides.'
    }
    foreach ($value in @($ApprovedSubscriptionId, $ApprovedTenantId)) {
        $parsed = [guid]::Empty
        if (-not [guid]::TryParseExact($value, 'D', [ref]$parsed) -or $parsed -eq [guid]::Empty) {
            throw 'configuration_required: privately configure the immutable approved lab subscription/tenant before authentication.'
        }
    }
    if ($Config.subscription_id -ne $ApprovedSubscriptionId -or $Config.tenant_id -ne $ApprovedTenantId) {
        throw 'scope_mismatch: settings must match the immutable approved lab scope, not the corporate default.'
    }
    if ($Config.node_vm_size -notin @('Standard_D4pls_v6', 'Standard_D4pls_v5') -or
        $Config.grant_audit_read_roles -isnot [bool] -or $Config.grant_demo_operator_role -isnot [bool] -or
        $Config.approved_thirty_day_budget_eur -isnot [long] -and $Config.approved_thirty_day_budget_eur -isnot [int] -or
        $Config.approved_thirty_day_budget_eur -lt 0) {
        throw 'invalid_configuration: declared VM SKU, boolean role gates and non-negative integer EUR budget are required.'
    }
    foreach ($field in @('audit_principal_id', 'demo_operator_principal_id')) {
        if ($Config[$field]) {
            $parsed = [guid]::Empty
            if (-not [guid]::TryParseExact($Config[$field], 'D', [ref]$parsed) -or $parsed -eq [guid]::Empty) {
                throw "invalid_configuration: $field must be an explicit GUID or empty."
            }
        }
    }
    if (($Config.grant_audit_read_roles -and -not $Config.audit_principal_id) -or
        ($Config.grant_demo_operator_role -and -not $Config.demo_operator_principal_id) -or
        ($Config.demo_operator_principal_id -and $Config.demo_operator_principal_id -eq $Config.audit_principal_id)) {
        throw 'identity_separation_required: explicit separate audit and optional human demo principals are required.'
    }
}

function Assert-DeploymentApproval {
    param([hashtable]$Config)
    if (-not $ApproveSpend -or -not $ApproveSchedulerRole -or $Config.approved_thirty_day_budget_eur -le 0 -or
        $Config.approval_reference -isnot [string] -or -not $Config.approval_reference.Trim() -or $Config.approval_reference.Length -gt 120) {
        throw 'approval_required: exact positive budget/quote consent and NEW cluster-scoped scheduler IAM approval must precede every write.'
    }
    if (($Config.grant_audit_read_roles -and -not $ApproveAuditRoles) -or
        ($Config.grant_demo_operator_role -and -not $ApproveDemoRole)) {
        throw 'role_approval_required: the NEW cluster audit-read and optional human manifest roles need separate explicit approvals.'
    }
    if ($Config.kubernetes_version -notmatch '^\d+\.\d+\.\d+$') {
        throw 'configuration_required: choose a supported non-preview regional Kubernetes patch before deployment.'
    }
}

function Invoke-LabAz {
    param([string[]]$Arguments)
    $output = & az @Arguments --subscription $ApprovedSubscriptionId --only-show-errors --output json
    if ($LASTEXITCODE -ne 0) { throw "azure_cli_failed: explicit lab operation '$($Arguments[0..1] -join ' ')' exited $LASTEXITCODE." }
    if (-not $output) { throw 'missing_azure_response: a read or deployment JSON receipt was required.' }
    $parsed = $output -join "`n" | ConvertFrom-Json -AsHashtable -NoEnumerate
    if ($null -eq $parsed) { throw 'missing_azure_response: null is not a JSON receipt.' }
    Write-Output -NoEnumerate $parsed
}

function Get-NextMadridInstant {
    param([DateTimeOffset]$ReferenceUtc, [ValidateSet(9, 17)][int]$Hour)
    $zone = [TimeZoneInfo]::FindSystemTimeZoneById('Romance Standard Time')
    $local = [TimeZoneInfo]::ConvertTime($ReferenceUtc, $zone)
    $date = $local.Date.AddHours($Hour)
    $utc = [TimeZoneInfo]::ConvertTimeToUtc($date, $zone)
    if ($utc -le $ReferenceUtc.UtcDateTime.AddMinutes(5)) {
        $date = $date.AddDays(1)
        $utc = [TimeZoneInfo]::ConvertTimeToUtc($date, $zone)
    }
    return [pscustomobject]@{local_time = $date.ToString('yyyy-MM-ddTHH:mm:ss'); time_zone = 'Europe/Madrid';
                            utc = $utc.ToString('yyyy-MM-ddTHH:mm:ssZ')}
}

function Get-DemoForecast {
    param([hashtable]$Rates, [ValidateSet('Standard_D4pls_v6', 'Standard_D4pls_v5')][string]$VmSize)
    foreach ($key in @('vm_v6', 'vm_v5', 'os_disk', 'load_balancer', 'public_ip', 'automation', 'lb_data')) {
        if (-not $Rates.ContainsKey($key) -or [decimal]$Rates[$key].rate -le 0) { throw "missing_retail_rate: $key has no positive paid meter." }
    }
    $vm = [decimal]$Rates[$(if ($VmSize -eq 'Standard_D4pls_v6') { 'vm_v6' } else { 'vm_v5' })].rate
    $residual = 2 * [decimal]$Rates.os_disk.rate + 720 * ([decimal]$Rates.load_balancer.rate + [decimal]$Rates.public_ip.rate)
    $scheduler = 2 * 30 * 61 * [decimal]$Rates.automation.rate
    return [pscustomobject]@{
        currency = 'EUR'; days = 30; node_vm_size = $VmSize; system_nodes = 2
        scheduled_node_hours_each = 240; node_hours_with_stop_allowance_each = 270
        compute_scheduled = 2 * 240 * $vm; residual_disk_lb_ip = $residual
        scheduler_max_minutes = 3660; free_scheduler_minutes_assumed = 0; scheduler_max = $scheduler
        base_before_scheduler_and_variables = 2 * 240 * $vm + $residual
        with_one_hour_daily_stop_allowance_and_max_scheduler = 2 * 270 * $vm + $residual + $scheduler
        stop_failure_24x7_before_variables = 2 * 720 * $vm + $residual + $scheduler
        optional_public_service_extra_ip = 720 * [decimal]$Rates.public_ip.rate
        optional_internal_lb_extra = 720 * [decimal]$Rates.load_balancer.rate
        budget_is_hard_cap = $false
        exclusions = @('tax', 'customer discounts', 'initial validation runtime', 'upgrade surge', 'bandwidth and processed data')
        stop_allowance_is_a_model_not_a_guarantee = $true
    }
}

function Get-FreshRetailRates {
    $reference = Get-Content -LiteralPath (Join-Path $AssetRoot 'retail-price-reference.json') -Raw | ConvertFrom-Json -AsHashtable
    $filter = '(' + (($reference.rates.Values | ForEach-Object { "meterId eq '$($_.meter_id)'" }) -join ' or ') + ") and priceType eq 'Consumption'"
    $uri = 'https://prices.azure.com/api/retail/prices?currencyCode=%27EUR%27&%24filter=' + [uri]::EscapeDataString($filter)
    $items = @()
    for ($page = 0; $uri; $page++) {
        if ($page -ge 5) { throw 'retail_paging_cap: no incomplete rate set is accepted.' }
        $next = [uri]$uri
        if ($next.Scheme -ne 'https' -or $next.Host -ne 'prices.azure.com' -or $next.Port -ne 443 -or
            $next.AbsolutePath -ne '/api/retail/prices' -or $next.UserInfo -or $next.Fragment) { throw 'unsafe_retail_continuation.' }
        $data = Invoke-RestMethod -Uri $next.AbsoluteUri -TimeoutSec 30 -MaximumRedirection 0
        $items += @($data.Items)
        $uri = $data.NextPageLink
    }
    $rates = @{}
    foreach ($key in $reference.rates.Keys) {
        $expected = $reference.rates[$key]
        $matches = @($items | Where-Object { $_.meterId -eq $expected.meter_id -and $_.currencyCode -eq 'EUR' -and
            $_.unitOfMeasure -eq $expected.unit -and $_.armRegionName -in @('swedencentral', 'Global') -and $_.retailPrice -gt 0 })
        if (-not $matches.Count) { throw "retail_rate_unavailable: $key; no static-reference or zero-cost fallback." }
        $selected = $matches | Sort-Object retailPrice -Descending | Select-Object -First 1
        $rates[$key] = @{meter_id = $expected.meter_id; unit = $selected.unitOfMeasure; rate = [decimal]$selected.retailPrice;
                        currency = 'EUR'; effective_start = $selected.effectiveStartDate; tier_minimum_units = $selected.tierMinimumUnits}
    }
    return $rates
}

function Get-DemoPreflight {
    param([hashtable]$Config)
    $account = Invoke-LabAz @('account', 'show')
    if ($account.id -ne $ApprovedSubscriptionId -or $account.tenantId -ne $ApprovedTenantId) { throw 'operator_tenant_mismatch.' }
    $skus = Invoke-LabAz @('vm', 'list-skus', '--location', 'swedencentral', '--resource-type', 'virtualMachines',
        '--size', $Config.node_vm_size, '--all', '--query', "[?name=='$($Config.node_vm_size)']")
    if ($skus.Count -ne 1 -or @($skus[0].restrictions | Where-Object { $_.type -eq 'Location' }).Count) {
        throw 'sku_unavailable: exact lab SKU is absent/restricted; no silent larger/Spot/burstable substitute.'
    }
    $capabilities = @{}
    foreach ($value in $skus[0].capabilities) { $capabilities[$value.name] = $value.value }
    if ([int]$capabilities.vCPUs -lt 4 -or [decimal]$capabilities.MemoryGB -lt 4 -or $capabilities.CpuArchitectureType -ne 'Arm64') {
        throw 'unsupported_system_sku: at least four vCPUs/four GB and the declared Arm64 architecture are required.'
    }
    $usage = Invoke-LabAz @('vm', 'list-usage', '--location', 'swedencentral')
    foreach ($name in @('cores', $skus[0].family)) {
        $row = @($usage | Where-Object { $_.name.value -eq $name })
        if ($row.Count -ne 1 -or [int]$row[0].limit - [int]$row[0].currentValue -lt 12) {
            throw "quota_unverified_or_insufficient: $name needs eight node cores plus four temporary upgrade-surge cores."
        }
    }
    $network = Invoke-LabAz @('network', 'list-usages', '--location', 'swedencentral')
    foreach ($name in @('PublicIPAddresses', 'StandardSkuLoadBalancers')) {
        $row = @($network | Where-Object { $_.name.value -eq $name })
        if ($row.Count -ne 1 -or [int]$row[0].limit - [int]$row[0].currentValue -lt 1) { throw "network_quota_unverified: $name." }
    }
    $versions = Invoke-LabAz @('aks', 'get-versions', '--location', 'swedencentral')
    if ($Mode -eq 'Deploy') {
        $patches = @()
        if ($versions.ContainsKey('values')) {
            foreach ($version in $versions.values) {
                if ($version.ContainsKey('isPreview') -and $version.isPreview -eq $false -and $version.ContainsKey('patchVersions')) {
                    $patches += @($version.patchVersions.Keys)
                }
            }
        } elseif ($versions.ContainsKey('orchestrators')) {
            $patches = @($versions.orchestrators | Where-Object { $_.ContainsKey('isPreview') -and $_.isPreview -eq $false } |
                        ForEach-Object { $_.kubernetesVersion })
        } else { throw 'regional_version_shape_unknown: no deployment is attempted.' }
        if ($Config.kubernetes_version -notin $patches) { throw 'regional_patch_not_verified: no unsupported/preview patch is deployed.' }
    }
    $rates = Get-FreshRetailRates
    return @{
        state = 'READ_ONLY_PREFLIGHT_NOT_PROVISIONED'; reference_utc = [DateTimeOffset]::UtcNow.ToString('o')
        subscription_id = $ApprovedSubscriptionId; tenant_id = $ApprovedTenantId
        selected_sku = $skus[0]; compute_quotas = $usage; network_quotas = $network; regional_versions = $versions
        rates = $rates; forecast = Get-DemoForecast $rates $Config.node_vm_size
        calculated_next_start = Get-NextMadridInstant ([DateTimeOffset]::UtcNow) 9
        calculated_next_stop = Get-NextMadridInstant ([DateTimeOffset]::UtcNow) 17
        native_schedules_created = $false; budget_is_hard_cap = $false
    }
}

function Get-DemoReadback {
    $cluster = Invoke-LabAz @('aks', 'show', '--resource-group', $ResourceGroup, '--name', $ClusterName)
    $clusterId = "/subscriptions/$ApprovedSubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.ContainerService/managedClusters/$ClusterName"
    if ($cluster.id -ne $clusterId) { throw 'cluster_readback_scope_mismatch.' }
    $accountId = "/subscriptions/$ApprovedSubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Automation/automationAccounts/$AutomationName"
    $account = Invoke-LabAz @('rest', '--method', 'get', '--url', "https://management.azure.com$accountId`?api-version=$AutomationApi")
    $schedules = @()
    foreach ($name in @('Madrid-Daily-0900', 'Madrid-Daily-1700')) {
        $schedule = Invoke-LabAz @('rest', '--method', 'get', '--url', "https://management.azure.com$accountId/schedules/$name`?api-version=$AutomationApi")
        if ($schedule.properties.frequency -ne 'Day' -or [int]$schedule.properties.interval -ne 1 -or
            $schedule.properties.timeZone -ne 'Europe/Madrid' -or -not $schedule.properties.isEnabled -or -not $schedule.properties.nextRun) {
            throw 'schedule_readback_incomplete: enabled daily Madrid definition AND actual native nextRun are required.'
        }
        $next = [DateTimeOffset]$schedule.properties.nextRun
        $local = [TimeZoneInfo]::ConvertTime($next, [TimeZoneInfo]::FindSystemTimeZoneById('Romance Standard Time'))
        $hour = if ($name -eq 'Madrid-Daily-0900') { 9 } else { 17 }
        if ($local.Hour -ne $hour -or $local.Minute -ne 0 -or $local.Second -ne 0 -or $next -le [DateTimeOffset]::UtcNow) {
            throw 'schedule_next_run_mismatch: native nextRun does not actually match the requested Madrid wall-clock time.'
        }
        $schedules += @{id = $schedule.id; name = $name; frequency = $schedule.properties.frequency;
            interval = $schedule.properties.interval; time_zone = $schedule.properties.timeZone;
            native_next_run_utc = ([DateTimeOffset]$schedule.properties.nextRun).UtcDateTime.ToString('o')}
    }
    $links = Invoke-LabAz @('rest', '--method', 'get', '--url', "https://management.azure.com$accountId/jobSchedules`?api-version=$AutomationApi")
    if ($links.nextLink -or @($links.value).Count -ne 2) { throw 'job_link_readback_incomplete: exactly two unpaged scoped job links are required.' }
    $expectedLinks = @{'Madrid-Daily-0900' = 'Start'; 'Madrid-Daily-1700' = 'Stop'}
    foreach ($link in $links.value) {
        $name = $link.properties.schedule.name
        if (-not $expectedLinks.ContainsKey($name) -or $link.properties.runbook.name -ne $RunbookName -or
            $link.properties.parameters.Action -ne $expectedLinks[$name]) { throw 'job_link_target_mismatch.' }
        $expectedLinks.Remove($name)
    }
    $roles = Invoke-LabAz @('role', 'assignment', 'list', '--scope', $clusterId, '--assignee-object-id', $account.identity.principalId,
                          '--include-inherited', '--all')
    if (@($roles).Count -ne 1 -or $roles[0].scope -ne $clusterId) { throw 'scheduler_role_scope_mismatch.' }
    $roleId = $roles[0].roleDefinitionId
    if ($roleId -notmatch "^/subscriptions/$ApprovedSubscriptionId/(resourceGroups/$ResourceGroup/)?providers/Microsoft.Authorization/roleDefinitions/[0-9a-f-]{36}$") {
        throw 'unsafe_role_definition_reference: no arbitrary source-derived URL or scope is read.'
    }
    $role = Invoke-LabAz @('rest', '--method', 'get', '--url', "https://management.azure.com$roleId`?api-version=2022-04-01")
    $wanted = @('Microsoft.ContainerService/managedClusters/read', 'Microsoft.ContainerService/managedClusters/start/action',
                'Microsoft.ContainerService/managedClusters/stop/action')
    $permissions = @($role.properties.permissions)
    if ($permissions.Count -ne 1 -or @($permissions[0].actions).Count -ne 3 -or
        @($permissions[0].actions | Where-Object { $_ -notin $wanted }).Count -or @($permissions[0].dataActions).Count -or
        @($permissions[0].notActions).Count -or @($permissions[0].notDataActions).Count) {
        throw 'scheduler_permission_mismatch: no extra ARM/data-plane privileges are accepted.'
    }
    return @{state = 'NATIVE_CONFIGURATION_READBACK_NOT_A_WORKLOAD_HEALTH_PROOF'; reference_utc = [DateTimeOffset]::UtcNow.ToString('o');
             cluster_id = $clusterId; power_state = $cluster.powerState.code; provisioning_state = $cluster.provisioningState;
             scheduler_principal_id = $account.identity.principalId; role_scope = $roles[0].scope; role_actions = $permissions[0].actions;
             schedules = $schedules; job_links = $links.value; budget_is_hard_cap = $false; stop_start_cycle_verified = $false}
}

function Invoke-DemoDeployment {
    param([hashtable]$Config)
    Assert-DeploymentApproval $Config
    $preflight = Get-DemoPreflight $Config
    if ([decimal]$preflight.forecast.with_one_hour_daily_stop_allowance_and_max_scheduler -gt $Config.approved_thirty_day_budget_eur) {
        throw 'budget_quote_changed: current bounded forecast exceeds the approved EUR quote; no resource is created.'
    }
    $exists = Invoke-LabAz @('group', 'exists', '--name', $ResourceGroup)
    if ($exists) { throw 'target_not_unused: refuse to change any existing resource group; use readback and an explicit reviewed revision.' }
    $artifactDirectory = Join-Path (Split-Path -Parent (Resolve-Path -LiteralPath $SettingsPath)) ('case04-operator-' + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $artifactDirectory | Out-Null
    $parameters = @{
        expectedSubscriptionId = $ApprovedSubscriptionId; expectedTenantId = $ApprovedTenantId
        approvedThirtyDayBudgetEur = $Config.approved_thirty_day_budget_eur; approvalReference = $Config.approval_reference
        kubernetesVersion = $Config.kubernetes_version; nodeVmSize = $Config.node_vm_size
        grantAuditReadRoles = $Config.grant_audit_read_roles; auditPrincipalId = $Config.audit_principal_id
        grantDemoOperatorRole = $Config.grant_demo_operator_role; demoOperatorPrincipalId = $Config.demo_operator_principal_id
    }
    $armParameters = @{parameters = @{}}
    foreach ($key in $parameters.Keys) { $armParameters.parameters[$key] = @{value = $parameters[$key]} }
    $parameterFile = Join-Path $artifactDirectory 'private-parameters.json'
    $armParameters | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $parameterFile -Encoding utf8
    Invoke-LabAz @('group', 'create', '--name', $ResourceGroup, '--location', 'swedencentral') | Out-Null
    $deployment = Invoke-LabAz @('deployment', 'group', 'create', '--resource-group', $ResourceGroup, '--name', 'case04-small-demo',
        '--template-file', (Join-Path $AssetRoot 'low-cost-aks.bicep'), '--parameters', "@$parameterFile")
    $schedulerPrincipal = $deployment.properties.outputs.schedulerPrincipalId.value
    $principalGuid = [guid]::Empty
    $expectedCluster = "/subscriptions/$ApprovedSubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.ContainerService/managedClusters/$ClusterName"
    if ($deployment.properties.provisioningState -ne 'Succeeded' -or $deployment.properties.outputs.clusterId.value -ne $expectedCluster -or
        -not [guid]::TryParseExact($schedulerPrincipal, 'D', [ref]$principalGuid) -or $principalGuid -eq [guid]::Empty -or
        $schedulerPrincipal -eq $Config.audit_principal_id -or $schedulerPrincipal -eq $Config.demo_operator_principal_id) {
        throw 'deployment_identity_readback_failed: inspect partial resources; no runbook is published or auto-cleanup attempted.'
    }
    $source = Get-Content -LiteralPath (Join-Path $AssetRoot 'Power-Control.ps1') -Raw
    $source = $source.Replace('<APPROVED_LAB_SUBSCRIPTION_ID>', $ApprovedSubscriptionId).Replace('<APPROVED_TENANT_ID>', $ApprovedTenantId).
        Replace('<NEW_AUTOMATION_PRINCIPAL_ID>', $schedulerPrincipal)
    $runbookFile = Join-Path $artifactDirectory 'private-power-control.ps1'
    [IO.File]::WriteAllText($runbookFile, $source.Replace("`r`n", "`n"), [Text.UTF8Encoding]::new($false))
    $accountId = $deployment.properties.outputs.automationId.value
    if ($accountId -ne "/subscriptions/$ApprovedSubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Automation/automationAccounts/$AutomationName") {
        throw 'automation_scope_mismatch: no arbitrary returned account/source URL is used.'
    }
    $base = "https://management.azure.com$accountId/runbooks/$RunbookName"
    & az rest --subscription $ApprovedSubscriptionId --method put --url "$base/draft/content`?api-version=$AutomationApi" `
        --headers 'Content-Type=text/plain' --body "@$runbookFile" --only-show-errors --output none
    if ($LASTEXITCODE -ne 0) { throw 'runbook_upload_failed: no schedule is linked.' }
    & az rest --subscription $ApprovedSubscriptionId --method post --url "$base/publish`?api-version=$AutomationApi" `
        --only-show-errors --output none
    if ($LASTEXITCODE -ne 0) { throw 'runbook_publish_failed: no schedule is linked.' }
    $runbook = Invoke-LabAz @('rest', '--method', 'get', '--url', "$base`?api-version=$AutomationApi")
    if ($runbook.properties.state -ne 'Published') { throw 'runbook_not_published: no schedule is linked.' }
    $start = Get-NextMadridInstant ([DateTimeOffset]::UtcNow) 9
    $stop = Get-NextMadridInstant ([DateTimeOffset]::UtcNow) 17
    Invoke-LabAz @('deployment', 'group', 'create', '--resource-group', $ResourceGroup, '--name', 'case04-daily-power',
        '--template-file', (Join-Path $AssetRoot 'daily-schedules.bicep'), '--parameters',
        "startTimeUtc=$($start.utc)", "stopTimeUtc=$($stop.utc)",
        "startJobScheduleId=$([guid]::NewGuid())", "stopJobScheduleId=$([guid]::NewGuid())") | Out-Null
    $receipt = Get-DemoReadback
    $receipt | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath (Join-Path $artifactDirectory 'native-readback.json') -Encoding utf8
    return $receipt
}

if ($MyInvocation.InvocationName -ne '.') {
    $config = Get-Content -LiteralPath $SettingsPath -Raw | ConvertFrom-Json -AsHashtable
    Assert-OperatorConfiguration $config
    $result = switch ($Mode) {
        Preflight { Get-DemoPreflight $config }
        Deploy { Invoke-DemoDeployment $config }
        Readback { Get-DemoReadback }
    }
    $result | ConvertTo-Json -Depth 20
}
