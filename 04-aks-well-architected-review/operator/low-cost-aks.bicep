targetScope = 'resourceGroup'

@description('Explicit approved lab subscription. The operator helper verifies this before any write.')
param expectedSubscriptionId string
@description('Explicit approved tenant; never inferred from the default CLI account.')
param expectedTenantId string
@minValue(1)
param approvedThirtyDayBudgetEur int
@minLength(1)
@maxLength(120)
param approvalReference string
@allowed(['swedencentral'])
param location string = 'swedencentral'
@allowed(['Standard_D4pls_v6', 'Standard_D4pls_v5'])
param nodeVmSize string = 'Standard_D4pls_v6'
@description('A currently supported, non-preview regional Kubernetes patch from preflight.')
param kubernetesVersion string
param grantAuditReadRoles bool = false
param auditPrincipalId string = ''
param grantDemoOperatorRole bool = false
param demoOperatorPrincipalId string = ''

var clusterName = 'aks-sre-demo-small'
var automationName = 'aa-aks-sre-demo-small'
var runbookName = 'Control-DemoAksPower'
var powerActions = [
  'Microsoft.ContainerService/managedClusters/read'
  'Microsoft.ContainerService/managedClusters/start/action'
  'Microsoft.ContainerService/managedClusters/stop/action'
]
var tags = {
  case: '04-aks-well-architected-review'
  environment: 'LAB'
  approvedThirtyDayBudgetEur: string(approvedThirtyDayBudgetEur)
  approvalReference: approvalReference
  budgetIsHardCap: 'false'
  expectedSubscriptionId: expectedSubscriptionId
  expectedTenantId: expectedTenantId
}

resource cluster 'Microsoft.ContainerService/managedClusters@2025-05-01' = {
  name: clusterName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: 'Base'
    tier: 'Free'
  }
  properties: {
    kubernetesVersion: kubernetesVersion
    dnsPrefix: '${clusterName}-${uniqueString(resourceGroup().id)}'
    nodeResourceGroup: 'rg-aks-sre-demo-small-nodes'
    enableRBAC: true
    disableLocalAccounts: true
    aadProfile: {
      managed: true
      enableAzureRBAC: true
      tenantID: expectedTenantId
    }
    agentPoolProfiles: [
      {
        name: 'systempool'
        mode: 'System'
        count: 2
        vmSize: nodeVmSize
        osType: 'Linux'
        osSKU: 'AzureLinux3'
        osDiskType: 'Managed'
        osDiskSizeGB: 32
        type: 'VirtualMachineScaleSets'
        maxPods: 30
        enableAutoScaling: false
        enableNodePublicIP: false
        upgradeSettings: {
          maxSurge: '1'
        }
      }
    ]
    nodeProvisioningProfile: {
      mode: 'Manual'
    }
    networkProfile: {
      networkPlugin: 'azure'
      networkPluginMode: 'overlay'
      networkDataplane: 'cilium'
      networkPolicy: 'cilium'
      podCidr: '10.244.0.0/16'
      serviceCidr: '10.0.0.0/16'
      dnsServiceIP: '10.0.0.10'
      loadBalancerSku: 'standard'
      outboundType: 'loadBalancer'
      loadBalancerProfile: {
        managedOutboundIPs: {
          count: 1
        }
      }
    }
    oidcIssuerProfile: {
      enabled: true
    }
    securityProfile: {
      workloadIdentity: {
        enabled: true
      }
    }
    autoUpgradeProfile: {
      upgradeChannel: 'stable'
      nodeOSUpgradeChannel: 'NodeImage'
    }
  }
}

resource automation 'Microsoft.Automation/automationAccounts@2023-11-01' = {
  name: automationName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    sku: {
      name: 'Basic'
    }
    publicNetworkAccess: true
  }
}

resource runbook 'Microsoft.Automation/automationAccounts/runbooks@2023-11-01' = {
  parent: automation
  name: runbookName
  location: location
  properties: {
    description: 'Only the fixed new demo cluster; Action=Start/Stop; no Kubernetes, RBAC, compute or arbitrary targets.'
    runbookType: 'PowerShell72'
    logProgress: false
    logVerbose: false
    logActivityTrace: 0
    draft: {}
  }
}

resource powerRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(resourceGroup().id, 'case04-demo-power-role')
  properties: {
    roleName: 'Case04 demo AKS power control ${uniqueString(resourceGroup().id)}'
    description: 'Read/start/stop only. Assignable in the dedicated new RG; assigned only to its new AKS resource.'
    type: 'CustomRole'
    assignableScopes: [resourceGroup().id]
    permissions: [{
      actions: powerActions
      notActions: []
      dataActions: []
      notDataActions: []
    }]
  }
}

resource powerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: cluster
  name: guid(cluster.id, automation.id, powerRole.id)
  properties: {
    roleDefinitionId: powerRole.id
    principalId: automation.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

var auditRoles = [
  '4abbcc35-e782-43d8-92c5-2d3f1bd2253f'
  '7f6c6a51-bcf8-42ba-9220-52d62157d7db'
]
resource auditAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in auditRoles: if (grantAuditReadRoles) {
  scope: cluster
  name: guid(cluster.id, auditPrincipalId, role)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role)
    principalId: auditPrincipalId
    principalType: 'ServicePrincipal'
  }
}]

resource demoRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = if (grantDemoOperatorRole) {
  name: guid(resourceGroup().id, 'case04-demo-manifest-role')
  properties: {
    roleName: 'Case04 bounded demo manifest operator ${uniqueString(resourceGroup().id)}'
    description: 'New demo cluster only: namespace, Deployment and ClusterIP Service writes; no secrets, exec, admin or role bindings.'
    type: 'CustomRole'
    assignableScopes: [resourceGroup().id]
    permissions: [{
      actions: [
        'Microsoft.ContainerService/managedClusters/read'
        'Microsoft.ContainerService/managedClusters/listClusterUserCredential/action'
      ]
      notActions: []
      dataActions: [
        'Microsoft.ContainerService/managedClusters/core/namespaces/read'
        'Microsoft.ContainerService/managedClusters/core/namespaces/write'
        'Microsoft.ContainerService/managedClusters/apps/deployments/read'
        'Microsoft.ContainerService/managedClusters/apps/deployments/write'
        'Microsoft.ContainerService/managedClusters/apps/replicasets/read'
        'Microsoft.ContainerService/managedClusters/core/services/read'
        'Microsoft.ContainerService/managedClusters/core/services/write'
        'Microsoft.ContainerService/managedClusters/core/pods/read'
      ]
      notDataActions: []
    }]
  }
}
resource demoAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (grantDemoOperatorRole) {
  scope: cluster
  name: guid(cluster.id, demoOperatorPrincipalId, 'case04-demo-manifest-role')
  properties: {
    roleDefinitionId: demoRole!.id
    principalId: demoOperatorPrincipalId
    principalType: 'User'
  }
}

output clusterId string = cluster.id
output automationId string = automation.id
output schedulerPrincipalId string = automation.identity.principalId
output powerRoleId string = powerRole.id
output powerAssignmentId string = powerAssignment.id
output runbookId string = runbook.id
output budgetIsHardCap bool = false
