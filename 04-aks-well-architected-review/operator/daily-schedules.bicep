targetScope = 'resourceGroup'

@description('Future UTC instants computed from 09:00/17:00 Europe/Madrid; native timeZone keeps later DST changes correct.')
param startTimeUtc string
param stopTimeUtc string
@description('Fresh GUIDs for new job links. The operator refuses existing links instead of making duplicate daily jobs.')
param startJobScheduleId string
param stopJobScheduleId string

resource automation 'Microsoft.Automation/automationAccounts@2023-11-01' existing = {
  name: 'aa-aks-sre-demo-small'
}
resource runbook 'Microsoft.Automation/automationAccounts/runbooks@2023-11-01' existing = {
  parent: automation
  name: 'Control-DemoAksPower'
}
resource startSchedule 'Microsoft.Automation/automationAccounts/schedules@2023-11-01' = {
  parent: automation
  name: 'Madrid-Daily-0900'
  properties: {
    description: 'Start the new demo AKS at 09:00 Europe/Madrid every day; startup is not instant workload readiness.'
    frequency: 'Day'
    interval: 1
    startTime: startTimeUtc
    timeZone: 'Europe/Madrid'
  }
}
resource stopSchedule 'Microsoft.Automation/automationAccounts/schedules@2023-11-01' = {
  parent: automation
  name: 'Madrid-Daily-1700'
  properties: {
    description: 'Stop control plane and VMSS nodes at 17:00 Europe/Madrid every day; no scale-to-zero substitute.'
    frequency: 'Day'
    interval: 1
    startTime: stopTimeUtc
    timeZone: 'Europe/Madrid'
  }
}
resource startLink 'Microsoft.Automation/automationAccounts/jobSchedules@2023-11-01' = {
  parent: automation
  name: startJobScheduleId
  properties: {
    runbook: {name: runbook.name}
    schedule: {name: startSchedule.name}
    parameters: {Action: 'Start'}
  }
}
resource stopLink 'Microsoft.Automation/automationAccounts/jobSchedules@2023-11-01' = {
  parent: automation
  name: stopJobScheduleId
  properties: {
    runbook: {name: runbook.name}
    schedule: {name: stopSchedule.name}
    parameters: {Action: 'Stop'}
  }
}
output timeZone string = 'Europe/Madrid'
output startScheduleId string = startSchedule.id
output stopScheduleId string = stopSchedule.id
output startJobLinkId string = startLink.id
output stopJobLinkId string = stopLink.id
