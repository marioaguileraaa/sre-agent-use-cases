"""Native-shaped anonymized unit evidence, not real customer detections."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_arc_defender_tools import ARC_ALPHA, SUB, TENANT, REFERENCE, assessment, live, machine, parameters, sim

VM = f"/subscriptions/{SUB}/resourceGroups/demo/providers/Microsoft.Compute/virtualMachines/demo-vm"
VAULT = f"/subscriptions/{SUB}/resourceGroups/demo/providers/Microsoft.KeyVault/vaults/demo-vault"


def resource(resource_id=VM, resource_type="microsoft.compute/virtualmachines"):
    return live._resource_row({
        "id": resource_id, "name": resource_id.rsplit("/", 1)[-1], "type": resource_type,
        "location": "demo-region", "tags": {"Responsable": "DEMO owner", "token": "DO_NOT_EXPORT"},
    }, SUB)


def native_finding(resource_id=ARC_ALPHA, status="Unhealthy", risk="Medium"):
    row = assessment(resource_id)
    row["properties"]["status"]["code"] = status
    row["properties"]["risk"] = {"level": risk, "riskFactors": ["Vulnerabilities"]}
    row["properties"]["metadata"].update({
        "severity": "High", "assessmentType": "BuiltIn", "recommendationCategory": "Vulnerabilities",
        "remediationDescription": "Review <b>source patch evidence</b>; apply a separately approved update.",
    })
    return row


def attack_graph():
    entities = [{
        "entityInternalId": "node-" + str(i), "entityName": "DEMO-" + str(i),
        "entityType": "microsoft.compute/virtualmachines",
        "entityIdentifiers": {"azureResourceId": VM if i == 2 else VM + "/DEMO-network/" + str(i)},
    } for i in range(3)]
    return {
        "id": f"/subscriptions/{SUB}/providers/Microsoft.Security/attackpaths/demo-path",
        "name": "demo-path", "type": "microsoft.security/attackpaths",
        "properties": {
            "displayName": "Native-shaped test path", "riskLevel": "High",
            "riskFactors": ["Internet exposure"], "entryPoint": entities[0], "target": entities[2],
            "attackPathSteps": {"one": "Source step", "two": "Target step"},
            "graphComponent": {
                "entities": entities,
                "connections": [
                    {"sourceEntityInternalId": "node-0", "targetEntityInternalId": "node-1", "title": "routes traffic to"},
                    {"sourceEntityInternalId": "node-1", "targetEntityInternalId": "node-2", "title": "routes traffic to"},
                ],
                "insights": [{
                    "entityInternalId": "node-2", "title": "highRiskVulnerabilityInsights",
                    "additionalData": {
                        "highRiskVulnerabilityInsights": {"maxCvssScore": 9.8, "hasHighOrCritical": "true"},
                        "token": "DO_NOT_EXPORT",
                    },
                }],
            },
            "assessments": {"node-2": {VM + "/providers/Microsoft.Security/assessments/demo": []}},
            "manualRemediationSteps": "Restrict unnecessary exposure; review linked recommendations.",
        },
    }


class NativeRiskAndEvidenceTests(unittest.TestCase):
    def test_native_medium_is_not_technical_high_and_never_substituted(self):
        inventory = [live._inventory_row(machine(), SUB, REFERENCE)]
        records = [native_finding(), native_finding(status="Healthy", risk=None)]
        records[1]["id"] += "-healthy"
        findings, counts = live._normalize_findings(
            records, "defender_recommendations", inventory, SUB, REFERENCE
        )
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]["risk_level"], "Medium")
        self.assertEqual(findings[0]["technical_severity"], "High")
        self.assertEqual(findings[1]["risk_level"], "Not evaluated")
        self.assertEqual(findings[1]["status"], "Healthy")
        self.assertEqual(counts["non_actionable_records"], 1)
        live._enrich_inventory(inventory, findings, "LIVE")
        self.assertNotIn("review-findings", {
            row["action_id"] for row in live._actions(inventory, findings, [], "LIVE")
        })
        self.assertNotIn("<b>", findings[0]["remediation"])

    def test_general_scope_retains_sql_and_container_dependents(self):
        parent = resource(ARC_ALPHA, "microsoft.hybridcompute/machines")
        child_id = ARC_ALPHA.lower() + "/securityentitydata/sqlservers:demo:databases:test"
        child = resource(child_id, "sqlOnMachineDatabase")
        record = native_finding(child_id)
        record["properties"]["resourceDetails"] = {"Id": child_id, "ResourceType": "sqlOnMachineDatabase"}
        record["properties"]["additionalData"] = {"parentResource": ARC_ALPHA}
        findings, counts = live._normalize_findings(
            [record], "defender_recommendations", [parent, child], SUB, REFERENCE, arc_only=False
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(counts["excluded_sql_descendant_records"], 0)
        self.assertEqual(live._assessed_parent(record, child_id, {parent["resource_id"]}, SUB), parent["resource_id"])
        self.assertEqual(findings[0]["resource_type"], "sqlonmachinedatabase")

    def test_machine_sql_software_update_is_not_a_sql_database_descendant(self):
        record = native_finding()
        record["properties"]["displayName"] = "Update sql_server_2022"
        record["properties"]["additionalData"] = {"SoftwareName": "sql_server_2022"}
        findings, _ = live._normalize_findings(
            [record], "defender_recommendations", [live._inventory_row(machine(), SUB, REFERENCE)], SUB, REFERENCE
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["patch"]["software_name"], "sql_server_2022")

    def test_embedded_real_source_cves_and_kb_keep_fix_evidence_and_units(self):
        record = native_finding()
        record["properties"]["additionalData"] = {
            "SoftwareName": "sql_server_2022", "DetectedSoftwareVersions": '["16.0.1140.6"]',
            "Kbid": "5122771", "PatchName": "Source SQL update", "RebootBehavior": "CanRequestReboot",
            "CvesDetails": json.dumps([{
                "CveId": "CVE-2025-24999", "Severity": "Critical",
                "FixStatus": "FixAvailable", "FixedVersion": "",
            }] * 2),
            "remediationQuery": "DO_NOT_EXPORT_OR_EXECUTE", "token": "DO_NOT_EXPORT",
        }
        findings, _ = live._normalize_findings(
            [record], "defender_recommendations", [live._inventory_row(machine(), SUB, REFERENCE)], SUB, REFERENCE
        )
        self.assertEqual(findings[0]["risk_level"], "Medium")
        self.assertEqual(findings[0]["cve_details"][0]["technical_severity"], "Critical")
        self.assertEqual(findings[0]["cve_details"][0]["fixed_version"], "Not supplied")
        self.assertEqual(findings[0]["patch"]["kb"], "KB5122771")
        self.assertEqual(findings[0]["patch"]["detected_versions"], ["16.0.1140.6"])
        self.assertNotIn("DO_NOT_EXPORT", json.dumps(findings))

    def test_malformed_encoded_cves_fail_the_source_explicitly(self):
        record = native_finding()
        record["properties"]["additionalData"]["CvesDetails"] = "[malformed"
        with self.assertRaises(live.EvidenceError):
            live._normalize_findings(
                [record], "defender_recommendations", [live._inventory_row(machine(), SUB, REFERENCE)], SUB, REFERENCE
            )

    def test_missing_cves_are_not_manufactured_from_high_severity(self):
        record = native_finding()
        findings, _ = live._normalize_findings(
            [record], "defender_recommendations", [live._inventory_row(machine(), SUB, REFERENCE)], SUB, REFERENCE
        )
        self.assertEqual(findings[0]["cve_details"], [])
        self.assertEqual(findings[0]["assessment_type"], "BuiltIn")

    def test_subscription_root_assessments_are_retained_without_fake_resource_kind(self):
        record = native_finding("/subscriptions/" + SUB)
        self.assertEqual(live._assessment_resource_id(record, SUB), "/subscriptions/" + SUB)
        indexed = resource("/subscriptions/" + SUB, "microsoft.resources/subscriptions")
        findings, _ = live._normalize_findings(
            [record], "defender_recommendations", [indexed], SUB, REFERENCE, arc_only=False
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(len(live._subscription_recommendations([record], SUB, REFERENCE)), 1)

    def test_spanish_tags_are_allowlisted_and_production_translated(self):
        value = machine()
        value["tags"] = {"Entorno": "Produccion", "Responsable": "DEMO owner", "Departamento": "DEMO IT",
                         "Proyecto": "DEMO", "CentroCoste": "DEMO-001", "password": "DO_NOT_EXPORT"}
        row = live._inventory_row(value, SUB, REFERENCE)
        self.assertEqual(row["environment"], "Production")
        self.assertEqual(row["tags"]["CentroCoste"], "DEMO-001")
        self.assertNotIn("password", row["tags"])

    def test_safe_links_never_accept_injected_html_credentials_or_untrusted_hosts(self):
        for value in ("javascript:alert(1)", "https://portal.azure.com.evil.example/x",
                      "https://user@portal.azure.com/x", "https://evil.example/x",
                      "https://portal.azure.com/x?token=secret", "https://portal.azure.com/\nx"):
            self.assertEqual(live._safe_link(value), "")
        self.assertEqual(live._safe_link("portal.azure.com/#test"), "https://portal.azure.com/#test")


class GraphAndScopeTests(unittest.TestCase):
    def test_actual_three_nodes_two_edges_are_preserved_and_vm_is_not_arc(self):
        rows = live._normalize_attack_paths(
            [attack_graph()], [resource(), resource(ARC_ALPHA, "microsoft.hybridcompute/machines")], SUB, REFERENCE
        )
        path = rows[0]
        self.assertEqual((len(path["entities"]), len(path["edges"])), (3, 2))
        self.assertEqual(path["arc_resource_ids"], [])
        self.assertEqual(path["association"], "Other subscription resources")
        self.assertEqual(len(path["assessment_ids"]), 1)
        self.assertNotIn("DO_NOT_EXPORT", json.dumps(path))

    def test_single_entity_path_does_not_invent_edges(self):
        row = attack_graph()
        entity = row["properties"]["graphComponent"]["entities"][0]
        row["properties"].update({"entryPoint": entity, "target": entity})
        row["properties"]["graphComponent"] = {"entities": [entity], "connections": [], "insights": []}
        path = live._normalize_attack_paths([row], [resource()], SUB, REFERENCE)[0]
        self.assertEqual((len(path["entities"]), len(path["edges"])), (1, 0))

    def test_exact_arc_association_and_not_name_based(self):
        row = attack_graph()
        graph = row["properties"]["graphComponent"]
        for entity in graph["entities"]:
            if entity["entityInternalId"] == "node-2":
                entity["entityIdentifiers"]["azureResourceId"] = ARC_ALPHA.upper()
        row["properties"]["target"] = copy.deepcopy(graph["entities"][2])
        path = live._normalize_attack_paths(
            [row], [resource(ARC_ALPHA, "microsoft.hybridcompute/machines")], SUB, REFERENCE
        )[0]
        self.assertEqual(path["arc_resource_ids"], [ARC_ALPHA.lower()])

    def test_dangling_edges_and_conflicting_endpoints_are_source_errors(self):
        for mutate in ("edge", "endpoint"):
            row = attack_graph()
            if mutate == "edge":
                row["properties"]["graphComponent"]["connections"][0]["targetEntityInternalId"] = "missing"
            else:
                row["properties"]["target"] = copy.deepcopy(row["properties"]["target"])
                row["properties"]["target"]["entityName"] = "conflict"
            with self.subTest(mutate=mutate), self.assertRaises(live.EvidenceError):
                live._normalize_attack_paths([row], [resource()], SUB, REFERENCE)

    def test_cross_subscription_source_record_fails_closed(self):
        row = attack_graph()
        row["id"] = row["id"].replace(SUB, TENANT)
        with self.assertRaises(live.EvidenceError):
            live._normalize_attack_paths([row], [resource()], SUB, REFERENCE)

    def test_software_is_observed_inventory_not_sensor_or_complete_host_assurance(self):
        rows = [{
            "id": VM + "/providers/Microsoft.Security/softwareInventories/demo",
            "properties": {
                "azureVmId": VM, "softwareName": "demo", "version": "1", "vendor": "demo",
                "numberOfKnownVulnerabilities": 2, "orgId": "DO_NOT_EXPORT", "deviceId": "DO_NOT_EXPORT",
            },
        }]
        result = live._normalize_software(rows, [resource()], SUB, REFERENCE)
        self.assertEqual(result[0]["arc_resource_ids"], [])
        self.assertEqual(result[0]["known_vulnerabilities"], 2)
        self.assertNotIn("DO_NOT_EXPORT", json.dumps(result))

    def test_native_child_parent_requires_exact_known_id_or_unique_suffix(self):
        row = native_finding(VAULT + "___container")
        candidate = VAULT.lower() + "___container"
        self.assertEqual(live._assessed_parent(row, candidate, {VAULT.lower()}, SUB), VAULT.lower())
        self.assertEqual(live._assessed_parent(row, candidate, {VM.lower()}, SUB), "")


class PostureAndTransportTests(unittest.TestCase):
    def test_classic_score_and_control_gain_are_observed_and_scoped(self):
        row = {
            "id": f"/subscriptions/{SUB}/providers/Microsoft.Security/secureScores/ascScore/controls/test",
            "name": "test", "properties": {
                "displayName": "Remediate vulnerabilities", "score": {"current": 0.27, "max": 6, "percentage": 0.045},
                "healthyResourceCount": 1, "unhealthyResourceCount": 21, "notApplicableResourceCount": 29,
            },
        }
        normalized = live._normalize_context([row], "secure_score_controls", SUB, REFERENCE)[0]
        self.assertEqual(normalized["potential_score_gain"], 5.73)
        self.assertEqual(normalized["scope"], "Subscription context")
        self.assertEqual(normalized["unhealthy"], 21)
        row["properties"]["score"]["current"] = 8
        with self.assertRaises(live.EvidenceError):
            live._normalize_context([row], "secure_score_controls", SUB, REFERENCE)

    def test_native_risk_score_numerator_greater_than_denominator_never_becomes_percent(self):
        row = {
            "id": f"/subscriptions/{SUB}/providers/Microsoft.Security/riskSecureScore/All",
            "name": "All", "properties": {
                "assessmentCategory": "All", "secureScoreNumerator": 297.5, "secureScoreDenominator": 196,
            },
        }
        result = live._normalize_context([row], "risk_secure_score", SUB, REFERENCE)[0]
        self.assertEqual(result["native_numerator"], 297.5)
        self.assertNotIn("percentage", result)

    def test_compliance_unsupported_and_skipped_are_not_passed(self):
        row = {
            "id": f"/subscriptions/{SUB}/providers/Microsoft.Security/regulatoryComplianceStandards/test",
            "name": "test", "properties": {
                "state": "Failed", "passedControls": 40, "failedControls": 23,
                "skippedControls": 0, "unsupportedControls": 22,
            },
        }
        result = live._normalize_context([row], "compliance_standards", SUB, REFERENCE)[0]
        self.assertEqual(result["passedControls"], 40)
        self.assertEqual(result["unsupportedControls"], 22)
        self.assertNotIn("certified", result)

    def test_all_expanded_query_views_fit_exact_default_serializer(self):
        snapshot = sim._fixture(REFERENCE)
        for view in sim.VIEWS:
            with self.subTest(view=view):
                result = sim._query(snapshot, parameters(view=view, limit=100))
                self.assertLessEqual(len(json.dumps(result).encode("utf-8")), 3500)
                self.assertEqual(result["returned"], len(result["items"]))
                self.assertEqual(result["has_more"], result["returned"] < result["total_matched"])
                if result["has_more"]:
                    self.assertGreater(result["next_offset"], 0)

    def test_scope_specific_filters_are_rejected_instead_of_silently_ignored(self):
        for view in ("posture", "controls", "compliance"):
            result = sim.main(operation="query", view=view, server_name="demo")
            self.assertEqual(result["status"], "error")
        result = sim.main(operation="query", view="inventory", association="arc")
        self.assertEqual(result["status"], "error")

    def test_native_risk_status_and_type_filters_use_local_evidence(self):
        result = sim.main(operation="query", view="findings", risk="Medium", status="Unhealthy",
                          resource_type="Microsoft.HybridCompute/machines")
        self.assertGreater(result["returned"], 0)
        self.assertTrue(all(r["risk_level"] == "Medium" and r["status"] == "Unhealthy" for r in result["items"]))
        for value in ("resources | union securityresources", "https://evil.example", "../escape"):
            self.assertEqual(sim.main(operation="query", resource_type=value)["status"], "error")

    def test_simulation_contains_only_illustrative_chains_and_demo_cves(self):
        snapshot = sim._fixture(REFERENCE)
        self.assertEqual(len(snapshot["attack_paths"]), 2)
        self.assertTrue(all(p["provenance"] == "SIMULATED" for p in snapshot["attack_paths"]))
        self.assertTrue(all(v["cve_id"].startswith("DEMO-VA-") for v in snapshot["vulnerabilities"]))
        self.assertNotIn("CVE-", json.dumps(snapshot))
        self.assertTrue(all(p["arc_resource_ids"] for p in snapshot["attack_paths"]))

    def test_live_is_customer_neutral_and_simulation_keeps_approved_brand(self):
        snapshot = sim._fixture(REFERENCE)
        simulated_html = sim._render_html(snapshot)
        self.assertIn('alt="Mercadona"', simulated_html)
        self.assertIn("Illustrative simulated attack chains", simulated_html)
        snapshot["provenance"] = "LIVE"
        snapshot["scope"] = {"description": "General subscription"}
        actual_html = live._render_html(snapshot)
        body = actual_html.split("<body", 1)[1].split('<script type="application/json"', 1)[0]
        self.assertNotIn('alt="Mercadona"', body)
        self.assertIn('class="live"', body)
        self.assertIn("Defender for Cloud posture", body)
        self.assertIn("Native risk", body)
        self.assertIn('id="detail-resource"', body)

    def test_complete_artifacts_and_long_runtime_paths_still_fit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "terminalRoot" / "tmp" / "ThreadFiles" / SUB
            root.mkdir(parents=True)
            with patch.object(sim.Path, "cwd", return_value=root):
                result = sim.main(operation="report")
            self.assertEqual(result["status"], "success")
            self.assertLessEqual(len(json.dumps(result).encode("utf-8")), 3500)
            snapshot = json.loads(Path(result["snapshot_path"]).read_text(encoding="utf-8"))
            self.assertEqual(len(snapshot["inventory"]), 200)
            for key in ("attack_paths", "software", "posture", "compliance", "vulnerabilities"):
                self.assertIn(key, snapshot)
            self.assertGreater(len(snapshot["vulnerabilities"]), 0)
            self.assertEqual(len(snapshot["attack_paths"]), 2)


if __name__ == "__main__":
    unittest.main()
