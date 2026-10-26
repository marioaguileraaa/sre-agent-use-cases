# Self-contained offline mocks: no Graph module, sign-in, installation or Pester dependency.
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "..\grant-graph-permission.ps1"
$source = Get-Content -LiteralPath $scriptPath -Raw
$tokens = $null
$parseErrors = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile(
    $scriptPath, [ref]$tokens, [ref]$parseErrors
)

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

Assert-True ($parseErrors.Count -eq 0) "The grant script must parse without errors."
Assert-True (
    [regex]::Matches($source, [regex]::Escape('"<YOUR_AGENT_CLIENT_ID>"')).Count -eq 1
) "The test must replace exactly one configuration placeholder."
$configuredSource = $source.Replace(
    '"<YOUR_AGENT_CLIENT_ID>"', '"11111111-1111-4111-8111-111111111111"'
)

function Invoke-Scenario {
    param(
        [switch]$Placeholder,
        [switch]$Existing,
        [switch]$VerboseOutput,
        [string]$FaultAt = "",
        [switch]$NonTerminating,
        [ValidateSet("", "identity", "graph", "role")]
        [string]$Missing = "",
        [switch]$CleanupFails
    )

    $ErrorActionPreference = "Continue"
    $VerbosePreference = "SilentlyContinue"
    $state = @{
        Calls = [System.Collections.Generic.List[string]]::new()
        Events = [System.Collections.Generic.List[string]]::new()
        Messages = [System.Collections.Generic.List[string]]::new()
        Filters = [System.Collections.Generic.List[string]]::new()
        ClientId = "11111111-1111-4111-8111-111111111111"
        GraphId = "22222222-2222-4222-8222-222222222222"
        IdentityId = "33333333-3333-4333-8333-333333333333"
        RoleId = "44444444-4444-4444-8444-444444444444"
        Grant = $null
        Scopes = @()
        AllAssignments = $false
    }

    function Invoke-MockCommand {
        param([string]$Name)
        [void]$state.Calls.Add($Name)
        [void]$state.Events.Add("call:$Name")
        if ($FaultAt -eq $Name) {
            if ($NonTerminating) {
                Write-Error "Mock $Name failure."
            }
            else {
                throw "Mock $Name failure."
            }
        }
        if ($CleanupFails -and $Name -eq "Disconnect-MgGraph") {
            throw "Mock Disconnect-MgGraph cleanup failure."
        }
    }

    function Install-Module {
        [CmdletBinding()]
        param([string]$Name, [string]$Scope, [switch]$Force)
        Invoke-MockCommand "Install-Module"
        Assert-True ($Name -eq "Microsoft.Graph" -and $Scope -eq "CurrentUser" -and $Force) "Installation scope changed."
    }

    function Import-Module {
        [CmdletBinding()]
        param([string]$Name)
        Invoke-MockCommand "Import-Module"
        Assert-True ($Name -eq "Microsoft.Graph.Applications") "Imported module changed."
    }

    function Connect-MgGraph {
        [CmdletBinding()]
        param([string[]]$Scopes)
        Invoke-MockCommand "Connect-MgGraph"
        $state.Scopes = $Scopes
        [pscustomobject]@{ MockSdkOutput = "Connection metadata" }
    }

    function Get-MgServicePrincipal {
        [CmdletBinding()]
        param([string]$Filter)
        Invoke-MockCommand "Get-MgServicePrincipal"
        [void]$state.Filters.Add($Filter)
        if ($Filter -eq "appId eq '$($state.ClientId)'") {
            if ($Missing -ne "identity") {
                [pscustomobject]@{ Id = $state.IdentityId }
            }
        }
        elseif ($Filter -eq "appId eq '00000003-0000-0000-c000-000000000000'") {
            if ($Missing -ne "graph") {
                $roles = @(
                    [pscustomobject]@{
                        Id = "55555555-5555-4555-8555-555555555555"
                        Value = "Application.Read.All"
                        AllowedMemberTypes = @("User")
                    }
                    [pscustomobject]@{
                        Id = "66666666-6666-4666-8666-666666666666"
                        Value = "AppRoleAssignment.ReadWrite.All"
                        AllowedMemberTypes = @("Application")
                    }
                )
                if ($Missing -ne "role") {
                    $roles += [pscustomobject]@{
                        Id = $state.RoleId
                        Value = "Application.Read.All"
                        AllowedMemberTypes = @("Application")
                    }
                }
                [pscustomobject]@{ Id = $state.GraphId; AppRoles = $roles }
            }
        }
        else {
            throw "Unexpected service-principal lookup; no live fallback is allowed."
        }
    }

    function Get-MgServicePrincipalAppRoleAssignment {
        [CmdletBinding()]
        param([string]$ServicePrincipalId, [switch]$All)
        Invoke-MockCommand "Get-MgServicePrincipalAppRoleAssignment"
        Assert-True ($ServicePrincipalId -eq $state.IdentityId) "Assignment lookup targets the wrong identity."
        $state.AllAssignments = [bool]$All
        [pscustomobject]@{ ResourceId = "77777777-7777-4777-8777-777777777777"; AppRoleId = $state.RoleId }
        [pscustomobject]@{ ResourceId = $state.GraphId; AppRoleId = "88888888-8888-4888-8888-888888888888" }
        if ($Existing) {
            [pscustomobject]@{ ResourceId = $state.GraphId; AppRoleId = $state.RoleId }
        }
    }

    function New-MgServicePrincipalAppRoleAssignment {
        [CmdletBinding()]
        param([string]$ServicePrincipalId, [hashtable]$BodyParameter)
        Invoke-MockCommand "New-MgServicePrincipalAppRoleAssignment"
        $state.Grant = @{ ServicePrincipalId = $ServicePrincipalId; Body = $BodyParameter }
        [pscustomobject]@{ MockSdkOutput = "Assignment metadata" }
    }

    function Disconnect-MgGraph {
        [CmdletBinding()]
        param()
        Invoke-MockCommand "Disconnect-MgGraph"
        [pscustomobject]@{ MockSdkOutput = "Disconnected metadata" }
    }

    function Write-Host {
        [CmdletBinding()]
        param([object]$Object, [string]$ForegroundColor)
        [void]$state.Messages.Add([string]$Object)
        [void]$state.Events.Add("host:$Object")
    }

    $records = [System.Collections.Generic.List[object]]::new()
    $failure = $null
    $block = [scriptblock]::Create($(if ($Placeholder) { $source } else { $configuredSource }))
    $arguments = @{}
    if ($VerboseOutput) {
        $arguments.Verbose = $true
    }
    try {
        & $block @arguments *>&1 | ForEach-Object { [void]$records.Add($_) }
    }
    catch {
        $failure = $_
    }
    [pscustomobject]@{ State = $state; Error = $failure; Records = $records.ToArray() }
}

$caseCount = 1
$placeholder = Invoke-Scenario -Placeholder
Assert-True ($placeholder.Error.Exception.Message.Contains("Replace <YOUR_AGENT_CLIENT_ID>")) "Placeholder must be rejected."
Assert-True ($placeholder.State.Calls.Count -eq 0 -and $placeholder.State.Messages.Count -eq 0) "Placeholder must not install, authenticate, grant or report progress."
$caseCount++

$new = Invoke-Scenario
Assert-True ($null -eq $new.Error) "A new assignment should succeed."
Assert-True ($new.Records.Count -eq 0) "Default progress must not emit SDK objects or verbose output."
Assert-True ($new.State.Scopes.Count -eq 2 -and $new.State.Scopes -contains "Application.Read.All" -and $new.State.Scopes -contains "AppRoleAssignment.ReadWrite.All") "Delegated operator scopes changed."
Assert-True ($new.State.AllAssignments) "All assignment pages must be requested."
Assert-True ($new.State.Grant.ServicePrincipalId -eq $new.State.IdentityId) "Grant targets the wrong service principal."
Assert-True ($new.State.Grant.Body.Count -eq 3 -and $new.State.Grant.Body.principalId -eq $new.State.IdentityId -and $new.State.Grant.Body.resourceId -eq $new.State.GraphId -and $new.State.Grant.Body.appRoleId -eq $new.State.RoleId) "Only the selected Application.Read.All app role must be assigned."
Assert-True ($new.State.Messages.Contains("Application.Read.All granted to the managed identity.")) "Existing grant-success text must be preserved."
Assert-True (@($new.State.Calls | Where-Object { $_ -eq "New-MgServicePrincipalAppRoleAssignment" }).Count -eq 1) "Exactly one new assignment is expected."
Assert-True (@($new.State.Calls | Where-Object { $_ -eq "Disconnect-MgGraph" }).Count -eq 1) "Successful sign-in must be disconnected once."

$phaseCommands = @{
    1 = "Install-Module"
    2 = "Import-Module"
    3 = "Connect-MgGraph"
    4 = "Get-MgServicePrincipal"
    5 = "Get-MgServicePrincipalAppRoleAssignment"
    7 = "Disconnect-MgGraph"
}
foreach ($phase in $phaseCommands.Keys) {
    $phaseEvents = @($new.State.Events | Where-Object { $_.StartsWith("host:[$phase/7]") })
    $command = "call:" + $phaseCommands[$phase]
    Assert-True ($phaseEvents.Count -eq 2) "Phase $phase needs visible start and completion messages."
    Assert-True ($new.State.Events.IndexOf($phaseEvents[0]) -lt $new.State.Events.IndexOf($command) -and $new.State.Events.IndexOf($phaseEvents[1]) -gt $new.State.Events.LastIndexOf($command)) "Phase $phase progress must surround its slow calls."
}
Assert-True ($new.State.Events.IndexOf("host:Application.Read.All granted to the managed identity.") -gt $new.State.Events.IndexOf("call:New-MgServicePrincipalAppRoleAssignment")) "Grant success must follow the completed assignment."
$caseCount++

$existing = Invoke-Scenario -Existing
Assert-True ($null -eq $existing.Error -and $null -eq $existing.State.Grant) "An existing assignment must not create a duplicate."
Assert-True ($existing.State.Messages.Contains("Application.Read.All is already assigned.")) "Existing idempotent-success text must be preserved."
Assert-True ($existing.State.AllAssignments -and $existing.State.Calls.Contains("Disconnect-MgGraph")) "Existing-assignment flow must retain paging and cleanup."
$caseCount++

$verbose = Invoke-Scenario -VerboseOutput
Assert-True ($null -eq $verbose.Error) "The -Verbose common parameter must work."
Assert-True (@($verbose.Records | Where-Object { $_ -is [System.Management.Automation.VerboseRecord] }).Count -ge 3) "-Verbose must provide useful non-secret phase detail."
Assert-True (@($verbose.Records | Where-Object { $_ -isnot [System.Management.Automation.VerboseRecord] }).Count -eq 0) "Verbose output must not contain SDK objects."
$caseCount++

$completionMessages = @{
    "Install-Module" = "[1/7] Microsoft.Graph installation completed."
    "Import-Module" = "[2/7] Microsoft.Graph.Applications imported."
    "Connect-MgGraph" = "[3/7] Microsoft Graph sign-in completed."
    "Get-MgServicePrincipal" = "[4/7] Managed identity and Application.Read.All application role found."
    "Get-MgServicePrincipalAppRoleAssignment" = "[5/7] Existing-assignment check completed."
    "New-MgServicePrincipalAppRoleAssignment" = "Application.Read.All granted to the managed identity."
    "Disconnect-MgGraph" = "[7/7] Microsoft Graph operator session disconnected."
}
foreach ($command in $completionMessages.Keys) {
    foreach ($nonTerminating in @($false, $true)) {
        $failed = Invoke-Scenario -FaultAt $command -NonTerminating:$nonTerminating
        Assert-True ($null -ne $failed.Error -and $failed.Error.Exception.Message.Contains("Mock $command failure.")) "A $command error must stop the script."
        Assert-True (-not $failed.State.Messages.Contains($completionMessages[$command])) "A failed $command must not print phase success."
        if ($command -ne "Disconnect-MgGraph") {
            Assert-True (-not $failed.State.Messages.Contains("Application.Read.All granted to the managed identity.")) "A failed operation must not report a grant."
        }
        $expectCleanup = $command -in @("Get-MgServicePrincipal", "Get-MgServicePrincipalAppRoleAssignment", "New-MgServicePrincipalAppRoleAssignment", "Disconnect-MgGraph")
        Assert-True ($failed.State.Calls.Contains("Disconnect-MgGraph") -eq $expectCleanup) "Cleanup must follow successful authentication, not a failed sign-in."
        $caseCount++
    }
}

foreach ($missing in @("identity", "graph", "role")) {
    $failed = Invoke-Scenario -Missing $missing
    Assert-True ($null -ne $failed.Error -and $null -eq $failed.State.Grant) "Missing $missing must fail without a grant."
    Assert-True (-not $failed.State.Messages.Contains("[4/7] Managed identity and Application.Read.All application role found.")) "Missing lookup data must not report success."
    Assert-True ($failed.State.Calls.Contains("Disconnect-MgGraph")) "Missing $missing must still disconnect."
    $caseCount++
}

$bothFailed = Invoke-Scenario -FaultAt "New-MgServicePrincipalAppRoleAssignment" -CleanupFails
Assert-True ($bothFailed.Error.Exception.Message.Contains("Mock New-MgServicePrincipalAppRoleAssignment failure.")) "Cleanup failure must not hide the original grant error."
Assert-True (@($bothFailed.Records | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] -and $_.Exception.Message.Contains("Mock Disconnect-MgGraph cleanup failure.") }).Count -eq 1) "Cleanup failure must also be surfaced."
Assert-True (-not $bothFailed.State.Messages.Contains("[7/7] Microsoft Graph operator session disconnected.")) "Failed cleanup must not report completion."
$caseCount++

Write-Host "$caseCount offline grant-script checks passed; no live Graph calls were made."
