import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from support import ROOT


OPERATOR = ROOT / "operator"
SHELL = shutil.which("pwsh") or shutil.which("powershell")


def ps_path(path):
    return "'" + str(path).replace("'", "''") + "'"


@unittest.skipUnless(SHELL, "PowerShell is required to execute the actual operator functions.")
class OperatorTests(unittest.TestCase):
    def run_ps(self, script):
        result = subprocess.run([SHELL, "-NoProfile", "-NonInteractive", "-Command", script],
                                text=True, encoding="utf-8", capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return json.loads(result.stdout)

    def operator_prefix(self):
        return ". " + ps_path(OPERATOR / "Demo-Operator.ps1") + "; "

    def power_prefix(self):
        return (
            ". " + ps_path(OPERATOR / "Power-Control.ps1") + " -Action Stop; "
            "$ApprovedSubscriptionId='11111111-1111-4111-8111-111111111111'; "
            "$ApprovedTenantId='22222222-2222-4222-8222-222222222222'; "
            "$ApprovedSchedulerPrincipalId='33333333-3333-4333-8333-333333333333'; "
            "$ClusterId='/subscriptions/'+$ApprovedSubscriptionId+'/resourceGroups/rg-aks-sre-demo-small/providers/Microsoft.ContainerService/managedClusters/aks-sre-demo-small'; "
        )

    def test_parse_actual_scripts(self):
        for name in ("Demo-Operator.ps1", "Power-Control.ps1"):
            result = self.run_ps(
                "$t=$null;$e=$null;[System.Management.Automation.Language.Parser]::ParseFile("
                + ps_path(OPERATOR / name) + ",[ref]$t,[ref]$e)|Out-Null;"
                "@{errors=@($e|ForEach-Object{$_.Message})}|ConvertTo-Json -Depth 4")
            self.assertEqual(result["errors"], [])

    def test_reference_forecast_is_exact_and_not_a_hard_cap(self):
        result = self.run_ps(self.operator_prefix()
                             + "$r=Get-Content " + ps_path(OPERATOR / "retail-price-reference.json")
                             + " -Raw|ConvertFrom-Json -AsHashtable; Get-DemoForecast $r.rates 'Standard_D4pls_v6'|ConvertTo-Json")
        self.assertEqual(result["base_before_scheduler_and_variables"], 85.0044)
        self.assertEqual(result["with_one_hour_daily_stop_allowance_and_max_scheduler"], 98.5644)
        self.assertEqual(result["stop_failure_24x7_before_variables"], 203.1444)
        self.assertEqual(result["scheduler_max_minutes"], 3660)
        self.assertEqual(result["free_scheduler_minutes_assumed"], 0)
        self.assertFalse(result["budget_is_hard_cap"])

    def test_dst_spring_fall_and_exact_boundary_all_seven_days(self):
        result = self.run_ps(self.operator_prefix() + """
            $cases=@(
                @('2026-03-28T00:00:00Z',9),@('2026-03-29T00:00:00Z',9),
                @('2026-10-24T00:00:00Z',17),@('2026-10-25T00:00:00Z',17),
                @('2026-10-25T08:00:00Z',9));
            $rows=@($cases|ForEach-Object{Get-NextMadridInstant ([DateTimeOffset]$_[0]) $_[1]});
            $rows|ConvertTo-Json -Depth 4
        """)
        self.assertEqual([row["utc"] for row in result], [
            "2026-03-28T08:00:00Z", "2026-03-29T07:00:00Z",
            "2026-10-24T15:00:00Z", "2026-10-25T16:00:00Z", "2026-10-26T08:00:00Z"])
        self.assertTrue(all(row["time_zone"] == "Europe/Madrid" for row in result))

    def test_missing_configuration_fails_before_any_azure_call(self):
        result = self.run_ps(self.operator_prefix() + """
            function Invoke-LabAz { throw 'SIMULATED-NETWORK-MUST-NOT-BE-CALLED' }
            $config=Get-Content """ + ps_path(OPERATOR / "settings.example.json") + """ -Raw|ConvertFrom-Json -AsHashtable;
            try { Assert-OperatorConfiguration $config; throw 'Unexpected success' }
            catch { @{error=$_.Exception.Message}|ConvertTo-Json }
        """)
        self.assertIn("configuration_required", result["error"])
        self.assertNotIn("SIMULATED-NETWORK", result["error"])

    def test_no_budget_approval_is_a_pre_auth_write_gate(self):
        result = self.run_ps(self.operator_prefix() + """
            function Get-DemoPreflight { throw 'SIMULATED-NETWORK-MUST-NOT-BE-CALLED' }
            $config=Get-Content """ + ps_path(OPERATOR / "settings.example.json") + """ -Raw|ConvertFrom-Json -AsHashtable;
            try { Invoke-DemoDeployment $config; throw 'Unexpected success' }
            catch { @{error=$_.Exception.Message}|ConvertTo-Json }
        """)
        self.assertIn("approval_required", result["error"])
        self.assertNotIn("SIMULATED-NETWORK", result["error"])

    def test_failed_retail_does_not_fall_back_to_reference_or_free(self):
        result = self.run_ps(self.operator_prefix() + """
            function Invoke-RestMethod { @{Items=@(); NextPageLink=$null} }
            try { Get-FreshRetailRates; throw 'Unexpected success' }
            catch { @{error=$_.Exception.Message}|ConvertTo-Json }
        """)
        self.assertIn("retail_rate_unavailable", result["error"])

    def test_already_stopped_is_one_scoped_read_with_no_write(self):
        result = self.run_ps(self.power_prefix() + """
            $script:calls=0;
            function Invoke-ClusterPowerRequest {param($Method,$Suffix='')
                if($Method-ne'GET'){throw 'SIMULATED-UNEXPECTED-WRITE'}
                $script:calls++;
                @{id=$ClusterId;properties=@{nodeProvisioningProfile=@{mode='Manual'};
                    agentPoolProfiles=@(@{type='VirtualMachineScaleSets'});
                    provisioningState='Succeeded';powerState=@{code='Stopped'}}}
            }
            $data=Invoke-DemoPower|ConvertFrom-Json -AsHashtable;
            $data.calls=$script:calls;$data|ConvertTo-Json
        """)
        self.assertEqual(result["calls"], 1)
        self.assertFalse(result["requested_transition"])
        self.assertEqual(result["observed_power_state"], "Stopped")

    def test_arm_acceptance_is_not_success_until_power_state_readback(self):
        result = self.run_ps(self.power_prefix() + """
            $script:gets=0;$script:posts=0;
            function Start-Sleep {param($Seconds)}
            function Invoke-ClusterPowerRequest {param($Method,$Suffix='')
                if($Method-eq'POST'){$script:posts++;return $null}
                $script:gets++;
                $state=if($script:gets-eq1){'Running'}else{'Stopped'};
                @{id=$ClusterId;properties=@{nodeProvisioningProfile=@{mode='Manual'};
                    agentPoolProfiles=@(@{type='VirtualMachineScaleSets'});
                    provisioningState='Succeeded';powerState=@{code=$state}}}
            }
            $data=Invoke-DemoPower|ConvertFrom-Json -AsHashtable;
            $data.gets=$script:gets;$data.posts=$script:posts;$data|ConvertTo-Json
        """)
        self.assertEqual(result["gets"], 2)
        self.assertEqual(result["posts"], 1)
        self.assertTrue(result["requested_transition"])
        self.assertEqual(result["observed_power_state"], "Stopped")

    def test_other_cluster_scope_is_rejected_before_post(self):
        result = self.run_ps(self.power_prefix() + """
            function Invoke-ClusterPowerRequest {param($Method,$Suffix='')
                if($Method-ne'GET'){throw 'SIMULATED-UNEXPECTED-WRITE'}
                @{id='/subscriptions/SIMULATED-OTHER/resourceGroups/original/providers/Microsoft.ContainerService/managedClusters/original'}}
            try { Invoke-DemoPower; throw 'Unexpected success' }
            catch { @{error=$_.Exception.Message}|ConvertTo-Json }
        """)
        self.assertIn("scope_mismatch", result["error"])

    def test_foreign_tenant_token_is_not_an_authentication_fallback(self):
        result = self.run_ps(self.power_prefix() + """
            $env:IDENTITY_ENDPOINT='http://127.0.0.1:12345/msi';$env:IDENTITY_HEADER='SIMULATED';
            $payload=@{tid='44444444-4444-4444-8444-444444444444';oid=$ApprovedSchedulerPrincipalId;
                aud='https://management.azure.com/';exp=([DateTimeOffset]::UtcNow.AddHours(1)).ToUnixTimeSeconds()}|ConvertTo-Json -Compress;
            $jwt='SIMULATED.'+[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($payload)).TrimEnd('=').Replace('+','-').Replace('/','_')+'.SIMULATED';
            function Invoke-RestMethod {@{access_token=$jwt}}
            try { Get-PowerToken; throw 'Unexpected success' }
            catch { @{error=$_.Exception.Message}|ConvertTo-Json }
        """)
        self.assertIn("identity_mismatch", result["error"])
        self.assertNotIn("SIMULATED.", result["error"])

    def test_demo_manifest_is_bounded_nonprivileged_and_no_extra_load_balancers(self):
        import yaml
        objects = list(yaml.safe_load_all((OPERATOR / "demo-workload.yaml").read_text(encoding="utf-8")))
        self.assertEqual([row["kind"] for row in objects], ["Namespace", "Deployment", "Service"])
        self.assertEqual(objects[2]["spec"]["type"], "ClusterIP")
        pod = objects[1]["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
        self.assertEqual(pod["containers"][0]["resources"]["limits"]["memory"], "128Mi")
        self.assertTrue(pod["containers"][0]["securityContext"]["readOnlyRootFilesystem"])
        self.assertFalse(pod["containers"][0]["securityContext"]["allowPrivilegeEscalation"])
        self.assertNotIn("secret", json.dumps(objects).lower())


if __name__ == "__main__":
    unittest.main()
