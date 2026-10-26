"""SIMULATED Recovery Services responses. No Azure identity or network access."""

import copy
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urlsplit


CASE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("case06_backup", CASE / "generate-azure-backup-report.py")
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)

SUBSCRIPTION = "00000000-0000-4000-8000-000000000001"
TENANT = "00000000-0000-4000-8000-000000000002"
CLIENT = "00000000-0000-4000-8000-000000000003"
REFERENCE = datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc)
VAULT_A = "/subscriptions/" + SUBSCRIPTION + "/resourceGroups/SIMULATED-a/providers/Microsoft.RecoveryServices/vaults/synthetic-vault"
VAULT_B = "/subscriptions/" + SUBSCRIPTION + "/resourceGroups/SIMULATED-b/providers/Microsoft.RecoveryServices/vaults/synthetic-vault"
VM_A = "/subscriptions/" + SUBSCRIPTION + "/resourceGroups/SIMULATED-a/providers/Microsoft.Compute/virtualMachines/same-name"
VM_B = "/subscriptions/" + SUBSCRIPTION + "/resourceGroups/SIMULATED-b/providers/Microsoft.Compute/virtualMachines/same-name"
VM_SHARED = "/subscriptions/" + SUBSCRIPTION + "/resourceGroups/SIMULATED-a/providers/Microsoft.Compute/virtualMachines/shared-sql-host"
ITEM_A = VAULT_A + "/backupFabrics/Azure/protectionContainers/IaasVMContainer;synthetic;rg;same-name/protectedItems/VM;synthetic;rg;same-name"
ITEM_B = VAULT_B + "/backupFabrics/Azure/protectionContainers/IaasVMContainer;synthetic;rg;same-name/protectedItems/VM;synthetic;rg;same-name"
ITEM_SQL_A = VAULT_A + "/backupFabrics/Azure/protectionContainers/VMAppContainer;synthetic/protectedItems/SQLDataBase;synthetic;database-a"
ITEM_SQL_B = VAULT_A + "/backupFabrics/Azure/protectionContainers/VMAppContainer;synthetic/protectedItems/SQLDataBase;synthetic;database-b"
BRANDING = {"name": "CLIENTE", "logo": "", "alt": "Customer logo"}
PRECISE_INTEGER = 900719925474099312345
HOSTILE_TEXT = '</script><img src="https://invalid.example/pixel" onerror="window.__injected=1"> & SIMULATED'


def config(verified=False):
    histories = {}
    if verified:
        for vault in (VAULT_A, VAULT_B):
            histories[vault.casefold()] = {
                "from_utc": TOOL.iso(REFERENCE - timedelta(days=14)), "through_utc": TOOL.iso(REFERENCE),
                "evidence": "SIMULATED interval receipt, not a real retention statement.",
            }
    return {"subscription_id": SUBSCRIPTION, "tenant_id": TENANT, "client_id": CLIENT,
            "vault_ids": [VAULT_A, VAULT_B], "history": histories}


def protected_item(identifier, source, name="same-name", status="Completed"):
    return {
        "id": identifier, "name": identifier.rsplit("/", 1)[-1],
        "type": "Microsoft.RecoveryServices/vaults/backupFabrics/protectionContainers/protectedItems",
        "properties": {
            "friendlyName": name, "backupManagementType": "AzureIaasVM", "workloadType": "VM",
            "protectedItemType": "Microsoft.Compute/virtualMachines", "sourceResourceId": source,
            "protectionState": "Protected", "protectionStatus": "Healthy", "healthStatus": "Passed",
            "lastBackupStatus": status, "lastBackupTime": "2026-10-14T04:00:00Z",
            "lastRecoveryPoint": "2026-10-14T04:05:00Z", "policyId": identifier.split("/backupFabrics/")[0] + "/backupPolicies/synthetic-policy",
            "syntheticPreciseInteger": PRECISE_INTEGER, "unmodeledSourceField": {"allFieldsRetained": HOSTILE_TEXT},
        },
    }


def job(name, status, operation="Backup", start="2026-10-14T05:00:00Z", vault=VAULT_A):
    return {
        "id": vault + "/backupJobs/" + name, "name": name, "type": "Microsoft.RecoveryServices/vaults/backupJobs",
        "properties": {
            "status": status, "operation": operation, "entityFriendlyName": "same-name",
            "backupManagementType": "AzureIaasVM", "jobType": "AzureIaaSVMJob", "startTime": start,
            "endTime": None if status == "InProgress" else "2026-10-14T05:02:03.2500000Z",
            "duration": "PT2M3.25S", "isUserTriggered": False, "syntheticPreciseInteger": PRECISE_INTEGER,
            "extendedInfo": {"tasksList": [{"taskId": "SIMULATED transfer", "status": status, "duration": "PT1M"}],
                             "propertyBag": {"VM Name": "same-name", "Unmodeled property": HOSTILE_TEXT}},
        },
    }


class FakeReader:
    """Only serves labeled synthetic objects; any unexpected read fails the test."""

    def __init__(self, extra_completed=0):
        self.calls, self.allowed, self.overrides = [], [], {}
        statuses = ["Failed", "CompletedWithWarnings", "Warning", "InProgress", "Completed", "Cancelled",
                    "NewNativeState", "CompletedWithWarning", "Canceled", "Warnings"]
        self.jobs_a = [job("synthetic-" + str(i), status) for i, status in enumerate(statuses)]
        self.jobs_a[0]["properties"]["errorDetails"] = [{"errorCode": 42, "errorTitle": "SIMULATED failure",
                                                        "errorString": "=SIMULATED source text " + HOSTILE_TEXT,
                                                        "recommendations": ["Human review only."]}]
        self.jobs_a[0]["properties"]["extendedInfo"]["propertyBag"]["Protected Item ID"] = ITEM_A.upper()
        self.jobs_a[1]["properties"]["warningDetails"] = [{"message": "SIMULATED warning"}]
        self.jobs_a[4]["properties"]["extendedInfo"]["propertyBag"]["Source Resource ID"] = VM_A
        self.jobs_a.extend([
            job("synthetic-restore", "Failed", "Restore"),
            job("synthetic-delete", "Completed", "DeleteBackupData"),
            job("synthetic-configure", "Completed", "ConfigureBackup"),
            job("synthetic-unknown-date", None, start="not-a-date"),
            job("synthetic-lower-bound", "Completed", start="2026-09-30T09:00:00Z"),
            job("synthetic-before-bound", "Completed", start="2026-09-30T08:59:59Z"),
            job("synthetic-upper-bound", "Completed", start="2026-10-14T09:00:00Z"),
            job("synthetic-transition", "Failed"),
            job("synthetic-ambiguous-id", "Completed"),
            job("synthetic-complete-with-evidence", "Completed"),
        ])
        self.jobs_a[-2]["properties"]["extendedInfo"]["propertyBag"]["Source Resource ID"] = VM_SHARED
        self.jobs_a[-1]["properties"]["errorDetails"] = [{"errorString": "SIMULATED native text with Completed; do not relabel it."}]
        self.jobs_a.extend(job("synthetic-extra-" + str(i), "Completed") for i in range(extra_completed))
        self.items_a = [protected_item(ITEM_A, VM_A), protected_item(ITEM_SQL_A, VM_SHARED, "sql-a"),
                        protected_item(ITEM_SQL_B, VM_SHARED, "sql-b", "Failed")]
        self.items_b = [protected_item(ITEM_B, VM_B)]
        self.details = {row["id"].casefold(): copy.deepcopy(row) for row in self.jobs_a}
        self.details[(VAULT_A + "/backupJobs/synthetic-transition").casefold()]["properties"]["status"] = "Completed"

    def allow(self, url):
        self.allowed.append(url)
        return url

    def request(self, url, source):
        self.calls.append((url, source))
        override = self.overrides.get(source)
        if override is not None:
            value = override(url) if callable(override) else override
            if isinstance(value, Exception):
                raise value
            return copy.deepcopy(value)
        parsed = urlsplit(url)
        path, query = parsed.path.casefold(), dict(parse_qsl(parsed.query))
        if path == ("/subscriptions/" + SUBSCRIPTION).casefold():
            return {"subscriptionId": SUBSCRIPTION, "tenantId": TENANT, "state": "Enabled", "displayName": "SIMULATED subscription"}
        for vault in (VAULT_A, VAULT_B):
            if path == vault.casefold():
                return {"id": vault, "name": "synthetic-vault", "location": "SIMULATED",
                        "properties": {"provisioningState": "Succeeded"}, "tags": {"provenance": "SIMULATED"}}
            if path == (vault + "/backupProtectedItems").casefold():
                rows = self.items_a if vault == VAULT_A else self.items_b
                if vault == VAULT_A and "$skipToken" not in query:
                    return {"value": copy.deepcopy(rows[:1]), "nextLink": url + "&" + urlencode({"$skipToken": "SIMULATED-items-next"}),
                            "syntheticPageField": {"preserve": True}}
                return {"value": copy.deepcopy(rows[1:] if vault == VAULT_A else rows), "syntheticPageField": "last"}
            if path == (vault + "/backupJobs").casefold():
                if vault == VAULT_B:
                    return {"value": [], "syntheticValidEmpty": True}
                if "$skipToken" not in query:
                    return {"value": copy.deepcopy(self.jobs_a[:7]), "nextLink": url + "&" + urlencode({"$skipToken": "<SIMULATED jobs next>"}),
                            "unmodeledEnvelope": {"integer": PRECISE_INTEGER, "text": HOSTILE_TEXT}}
                return {"value": copy.deepcopy(self.jobs_a[7:])}
        if path in self.details:
            return copy.deepcopy(self.details[path])
        raise AssertionError("Unexpected synthetic request: " + source + " " + url)


def simulated_snapshot(reader=None, verified=False, extra_completed=0, period="last_14d"):
    reader = reader or FakeReader(extra_completed=extra_completed)
    with patch.object(TOOL, "utc_now", return_value=REFERENCE + timedelta(seconds=20)):
        result = TOOL.collect_snapshot(reader, config(verified), period, REFERENCE)
    result["provenance"] = "SIMULATED"
    return result, reader
