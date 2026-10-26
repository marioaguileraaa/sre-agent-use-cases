"""Offline tests only: no Azure calls, tokens, customer data or primary checkout."""

import ast
import base64
import csv
import importlib.util
import io
import json
import socket
import sys
import tempfile
import types
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

SCENARIO = Path(__file__).resolve().parents[1]
REFERENCE = "2026-10-09T12:00:00Z"
SUB = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"
CLIENT_ID = "33333333-3333-4333-8333-333333333333"
ARC_ALPHA = f"/subscriptions/{SUB}/resourceGroups/Test-RG/providers/Microsoft.HybridCompute/machines/Alpha"
ARC_BETA = f"/subscriptions/{SUB}/resourceGroups/Test-RG/providers/Microsoft.HybridCompute/machines/Beta"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCENARIO / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


live = load("defender_live", "generate-defender-cloud-report.py")
sim = load("arc_sim", "simulate-arc-defender-mercadona.py")


def parameters(module=sim, **changes):
    values = {
        "operation": "query", "view": "inventory", "provider": "all", "environment": "all",
        "resource_group": "", "server_name": "", "connectivity": "all",
        "mde": "all", "severity": "all", "limit": 25, "offset": 0,
    }
    values.update(changes)
    return module._validate_parameters(**values)


def machine(resource_id=ARC_ALPHA, state="Connected", provider="N/A"):
    return {
        "id": resource_id, "name": resource_id.rsplit("/", 1)[-1],
        "tags": {"Environment": "Production", "secret": "DO_NOT_EXPORT_TAG"},
        "properties": {
            "status": state, "osName": "Windows Server 2022", "cloudMetadata": {"provider": provider},
            "lastStatusChange": "2026-06-10T08:00:00Z",
        },
    }


def extension(resource_id=ARC_ALPHA, state="Succeeded"):
    return {
        "id": resource_id + "/extensions/MDE.Windows", "name": "MDE.Windows",
        "properties": {
            "type": "MDE.Windows", "publisher": "Microsoft.Azure.AzureDefenderForServers",
            "provisioningState": state,
            "settings": {"token": "DO_NOT_EXPORT_EXTENSION_SETTINGS"},
            "protectedSettings": {"password": "DO_NOT_EXPORT_PROTECTED_SETTINGS"},
            "instanceView": {"status": {"message": "DO_NOT_EXPORT_RAW_INSTANCE_VIEW"}},
        },
    }


def assessment(resource_id=ARC_ALPHA, assessment_name="test", status="Unhealthy"):
    return {
        "id": resource_id + "/providers/Microsoft.Security/assessments/" + assessment_name,
        "name": assessment_name, "type": "microsoft.security/assessments",
        "properties": {
            "displayName": "Review endpoint onboarding",
            "resourceDetails": {"Id": resource_id.upper(), "Source": "Azure"},
            "metadata": {"severity": "High"},
            "status": {
                "code": status, "firstEvaluationDate": "2026-06-01T09:00:00Z",
                "statusChangeDate": "2026-06-02T09:00:00Z",
            },
            "additionalData": {"token": "DO_NOT_EXPORT_FINDING_EXTRA"},
        },
    }


class PayloadClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def request(self, method, url, source, body=None):
        self.calls.append((method, url, source, body))
        item = self.payloads.pop(0)
        if isinstance(item, live.EvidenceError):
            raise item
        return item


class LabRouter:
    fail_source = None
    fail_extension = False
    calls = []

    def __init__(self, token):
        self.token = token

    def close(self):
        pass

    def request(self, method, url, source, body=None):
        type(self).calls.append((method, url, source, body))
        if source == self.fail_source:
            raise live.EvidenceError("api_failed", "Mock denied source.", source, 403)
        if source == "scope_validation":
            return {"subscriptionId": SUB, "tenantId": TENANT}
        if source == "resource_inventory":
            rows = [{
                "id": rid, "name": rid.rsplit("/", 1)[-1], "type": "microsoft.hybridcompute/machines",
            } for rid in (ARC_ALPHA, ARC_BETA)]
            return {"data": rows, "count": 2, "totalRecords": 2, "resultTruncated": "false"}
        if source == "arc_inventory":
            return {"value": [machine(), machine(ARC_BETA, "Expired")]}
        if source == "arc_extensions":
            beta = "/machines/beta/" in url
            if beta and self.fail_extension:
                raise live.EvidenceError("api_failed", "Mock extension source unavailable.", source, 500)
            return {"value": [extension(ARC_BETA if beta else ARC_ALPHA, "Failed" if beta else "Succeeded")]}
        if source == "effective_servers_plan":
            return {"properties": {"pricingTier": "Standard", "subPlan": "P2", "inherited": "True"}}
        if source == "mde_integration":
            return {"properties": {"enabled": True}}
        if source == "defender_recommendations":
            if body["options"].get("$skipToken") == "page-two":
                return {
                    "data": [assessment(ARC_BETA, "second")], "count": 1, "totalRecords": 2,
                    "resultTruncated": "false",
                }
            return {
                "data": [assessment()], "count": 1, "totalRecords": 2,
                "resultTruncated": "false", "$skipToken": "page-two",
            }
        if source == "defender_vulnerabilities":
            return {"data": [], "count": 0, "totalRecords": 0, "resultTruncated": "false"}
        if source == "defender_alerts":
            return {"value": []}
        if source in live.CONTEXT_ARG_TYPES or source in ("compute_extensions", "aks_security_profiles"):
            return {"data": [], "count": 0, "totalRecords": 0, "resultTruncated": "false"}
        if source in ("subscription_secure_score", "subscription_plans", "compliance_standards"):
            return {"value": []}
        raise AssertionError("Unanticipated endpoint: " + source)


class ParameterTests(unittest.TestCase):
    def test_explicit_invalid_parameters_do_not_collect_or_write(self):
        cases = [
            {"operation": "delete"}, {"operation": 1}, {"provider": "https://evil.example"},
            {"view": "kql"}, {"environment": "random"},
            {"resource_group": "../unsafe"}, {"server_name": "x\n"},
            {"connectivity": "healthy"}, {"mde": "installed-is-healthy"}, {"severity": "Extreme"},
            {"limit": True}, {"limit": 0}, {"limit": 101}, {"limit": 1.0},
            {"offset": False}, {"offset": -1}, {"offset": 50001},
            {"server_name": "x" * 81}, {"resource_group": "x" * 91},
            {"operation": "report", "provider": "gcp"}, {"operation": "report", "limit": 1},
        ]
        for module in (live, sim):
            collector = "_collect_live" if module is live else "_fixture"
            with patch.object(module, collector) as collect:
                for case in cases:
                    with self.subTest(module=module.__name__, case=case):
                        result = module.main(**case)
                        self.assertEqual(result["status"], "error")
                        self.assertEqual(result["error"]["code"], "invalid_parameter")
                        self.assertNotIn("report_path", result)
                collect.assert_not_called()

    def test_enums_are_case_insensitive_but_scope_strings_never_become_kql(self):
        result = sim.main(operation="QUERY", provider="GCP", environment="production", limit=100)
        self.assertEqual(result["total_matched"], 28)
        injected = sim.main(operation="query", server_name="' | union securityresources")
        self.assertEqual(injected["total_matched"], 0)

    def test_unknown_arguments_are_not_a_tool_interface(self):
        with self.assertRaises(TypeError):
            sim.main(kql="resources")
        with self.assertRaises(TypeError):
            live.main(url="https://evil.example")

    def test_live_placeholders_fail_before_token_acquisition(self):
        with patch.object(live, "_get_token") as token:
            result = live.main(operation="query")
            self.assertEqual(result["error"]["code"], "configuration_required")
            token.assert_not_called()


class PaginationTests(unittest.TestCase):
    def test_arg_follows_skip_token_when_truncation_flag_is_false(self):
        client = PayloadClient([
            {"data": [{"id": "one"}], "count": 1, "totalRecords": 2,
             "resultTruncated": "false", "$skipToken": "next"},
            {"data": [{"id": "two"}], "count": 1, "totalRecords": 2, "resultTruncated": False},
        ])
        rows, pages = live._query_arg(client, "defender_recommendations", SUB)
        self.assertEqual((len(rows), pages), (2, 2))
        self.assertEqual(client.calls[1][3]["options"]["$skipToken"], "next")
        for method, _, _, body in client.calls:
            self.assertEqual(method, "POST")
            self.assertEqual(body["subscriptions"], [SUB])
            self.assertEqual(body["query"], live.ARG_QUERIES["defender_recommendations"])

    def test_arg_rejects_count_shape_truncation_missing_token_and_changed_snapshot(self):
        first = {"data": [{"id": "one"}], "count": 1, "totalRecords": 2,
                 "resultTruncated": "false", "$skipToken": "next"}
        cases = [
            [{"data": [], "count": 1, "totalRecords": 0, "resultTruncated": "false"}],
            [{"data": {}, "count": 0, "totalRecords": 0, "resultTruncated": "false"}],
            [{"data": [], "count": 0, "totalRecords": 2, "resultTruncated": "true"}],
            [{"data": [], "count": 0, "totalRecords": 1, "resultTruncated": "false"}],
            [{"data": [{"id": "one"}], "count": 1, "totalRecords": 1}],
            [first, {"data": [{"id": "two"}], "count": 1, "totalRecords": 3, "resultTruncated": "false"}],
            [first, {"data": [{"id": "one"}], "count": 1, "totalRecords": 2, "resultTruncated": "false"}],
            [first, {"data": [{"id": "two"}], "count": 1, "totalRecords": 2,
                     "resultTruncated": "false", "$skipToken": "next"}],
            [first, {"data": [], "count": 0, "totalRecords": 2,
                     "resultTruncated": "false", "$skipToken": "other"}],
        ]
        for responses in cases:
            with self.subTest(responses=responses), self.assertRaises(live.EvidenceError):
                live._query_arg(PayloadClient(responses), "defender_recommendations", SUB)

    def test_arm_follows_validated_pages(self):
        url = live.ARM_ORIGIN + f"/subscriptions/{SUB}/providers/Microsoft.HybridCompute/machines?api-version=2022-12-27"
        next_link = url + "&$skiptoken=opaque%2Btoken"
        client = PayloadClient([
            {"value": [machine()], "nextLink": next_link},
            {"value": [machine(ARC_BETA)]},
        ])
        rows, pages = live._list_arm(client, url, "arc_inventory")
        self.assertEqual((len(rows), pages), (2, 2))
        self.assertEqual(client.calls[1][1], next_link)

    def test_arm_rejects_cross_origin_cross_subscription_path_and_bad_parameters(self):
        url = live.ARM_ORIGIN + f"/subscriptions/{SUB}/providers/Microsoft.HybridCompute/machines?api-version=2022-12-27"
        unsafe = [
            url.replace("management.azure.com", "management.azure.com.evil.example"),
            url.replace("https://", "http://"),
            url.replace(SUB, TENANT), url.replace("/machines?", "/extensions?"),
            url.replace("2022-12-27", "9999-01-01"),
            url + "&url=https://evil.example", url + "#fragment",
            url.replace("management.azure.com", "user@management.azure.com"),
            url.replace("/providers/", "/../providers/"),
            url + "&api-version=2022-12-27",
        ]
        for link in unsafe:
            client = PayloadClient([{"value": [machine()], "nextLink": link}])
            with self.subTest(link=link), self.assertRaises(live.EvidenceError):
                live._list_arm(client, url, "arc_inventory")
            self.assertEqual(len(client.calls), 1)

    def test_arm_rejects_repeated_links_duplicate_ids_empty_pages_and_malformed_rows(self):
        url = live.ARM_ORIGIN + f"/subscriptions/{SUB}/providers/Microsoft.HybridCompute/machines?api-version=2022-12-27"
        cases = [
            [{"value": [machine()], "nextLink": url}],
            [{"value": [machine(), machine(ARC_ALPHA.upper())]}],
            [{"value": [], "nextLink": url + "&$skiptoken=x"}],
            [{"value": ["not-object"]}], [{"value": [{}]}], [{"value": [machine()], "nextLink": ""}],
        ]
        for responses in cases:
            with self.subTest(responses=responses), self.assertRaises(live.EvidenceError):
                live._list_arm(PayloadClient(responses), url, "arc_inventory")


class JoinTests(unittest.TestCase):
    def setUp(self):
        self.inventory = [
            live._inventory_row(machine(), SUB, REFERENCE),
            live._inventory_row(machine(ARC_BETA, "Expired"), SUB, REFERENCE),
        ]
        self.known = {r["resource_id"]: r for r in self.inventory}

    def test_pascal_case_resource_details_and_case_insensitive_ids(self):
        record = assessment()
        record["id"] = f"/subscriptions/{SUB}/providers/Microsoft.Security/assessments/global"
        record["properties"]["resourceDetails"] = {"ResourceId": ARC_ALPHA.upper() + "/", "Source": "Azure"}
        self.assertEqual(live._joined_arc_ids(record, self.known, SUB), [ARC_ALPHA.lower()])

    def test_arc_parent_assessment_and_subassessment_ids(self):
        record = assessment()
        record["properties"]["resourceDetails"] = {}
        record["id"] += "/subassessments/child"
        self.assertEqual(live._joined_arc_ids(record, self.known, SUB), [ARC_ALPHA.lower()])

    def test_nested_subassessment_details_and_alert_resource_identifiers(self):
        record = {
            "id": f"/subscriptions/{SUB}/providers/Microsoft.Security/assessments/global/subassessments/child",
            "properties": {"additionalData": {"resourceDetails": {"Id": ARC_BETA}}},
        }
        self.assertEqual(live._joined_arc_ids(record, self.known, SUB), [ARC_BETA.lower()])
        record["properties"] = {"ResourceIdentifiers": [{"Type": "AzureResource", "AzureResourceId": ARC_ALPHA}]}
        self.assertEqual(live._joined_arc_ids(record, self.known, SUB), [ARC_ALPHA.lower()])

    def test_names_workspaces_wrong_subscription_and_non_arc_ids_are_never_joined(self):
        records = [
            {"id": "global", "properties": {"resourceDetails": {"machineName": "Alpha", "workspaceId": "workspace"}}},
            {"id": ARC_ALPHA.replace(SUB, TENANT), "properties": {}},
            {"id": ARC_ALPHA.replace("Microsoft.HybridCompute", "Microsoft.Compute"), "properties": {}},
            {"id": "global", "properties": {"description": ARC_ALPHA}},
            {"id": ARC_ALPHA + "/evil-suffix", "properties": {}},
        ]
        for record in records:
            with self.subTest(record=record):
                self.assertEqual(live._joined_arc_ids(record, self.known, SUB), [])

    def test_all_assessment_statuses_preserved_and_evaluation_freshness_retained(self):
        unrelated = assessment(ARC_ALPHA.replace("Alpha", "not-in-inventory"), "other")
        records = [assessment(), assessment(ARC_BETA, "healthy", "Healthy"), unrelated]
        findings, counts = live._normalize_findings(records, "defender_recommendations", self.inventory, SUB, REFERENCE)
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[1]["status"], "Healthy")
        self.assertEqual(findings[0]["severity"], "High")
        self.assertEqual(findings[0]["first_evaluation_utc"], "2026-06-01T09:00:00Z")
        self.assertEqual(findings[0]["source_time_utc"], "2026-06-02T09:00:00Z")
        self.assertEqual(counts, {
            "arc_matched_records": 2, "excluded_unmatched_records": 1,
            "excluded_sql_descendant_records": 0, "non_actionable_records": 1,
        })
        self.assertIn("Retrieval time is not evaluation freshness", findings[0]["evidence"])

    def test_n_a_location_is_unknown_and_stale_arc_not_healthy(self):
        row = self.inventory[1]
        self.assertEqual(row["provider"], "unknown")
        self.assertEqual(row["connectivity"], "Expired")
        self.assertEqual(row["sensor_health"], "Unknown")
        self.assertIn("not verified", row["provider_evidence"])

    def test_malformed_times_do_not_turn_into_recent_heartbeats(self):
        value = machine()
        value["properties"]["lastStatusChange"] = "invalid"
        row = live._inventory_row(value, SUB, REFERENCE)
        self.assertIsNone(row["last_status_change_utc"])
        self.assertIn("missing/invalid", row["last_status_change_note"])

    def test_unknown_alert_status_does_not_invent_an_active_incident(self):
        record = {
            "id": f"/subscriptions/{SUB}/providers/Microsoft.Security/locations/test/alerts/id",
            "properties": {
                "resourceIdentifiers": [{"AzureResourceId": ARC_ALPHA}],
                "severity": "High", "status": "Unknown", "alertDisplayName": "Unverified alert status",
            },
        }
        findings, _ = live._normalize_findings(
            [record], "defender_alerts", self.inventory, SUB, REFERENCE
        )
        live._enrich_inventory(self.inventory, findings, "LIVE")
        alpha = next(r for r in self.inventory if r["server_name"] == "Alpha")
        self.assertNotEqual(alpha["priority"], "Immediate review")
        self.assertNotIn(
            "investigate-alerts", {a["action_id"] for a in live._actions(self.inventory, findings, [], "LIVE")}
        )

    def test_low_severity_findings_create_distinct_review_action_without_duplicate_sensor_action(self):
        record = assessment()
        record["properties"]["metadata"]["severity"] = "Low"
        findings, _ = live._normalize_findings(
            [record], "defender_recommendations", self.inventory, SUB, REFERENCE
        )
        live._enrich_inventory(self.inventory, findings, "LIVE")
        sources = [{"name": "mde_sensor_health", "status": "unavailable"}]
        actions = live._actions(self.inventory, findings, sources, "LIVE")
        ids = {a["action_id"] for a in actions}
        self.assertIn("verify-health", ids)
        self.assertIn("review-remaining-findings", ids)
        self.assertNotIn("restore-sources", ids)

    def test_malformed_status_is_source_error_not_guessed_risk(self):
        record = assessment()
        record["properties"]["status"]["code"] = {"unexpected": "shape"}
        with self.assertRaises(live.EvidenceError):
            live._normalize_findings([record], "defender_recommendations", self.inventory, SUB, REFERENCE)

    def test_sql_database_descendant_assessments_are_not_machine_findings(self):
        record = assessment()
        record["properties"]["resourceDetails"] = {
            "Id": ARC_ALPHA, "ResourceType": "sqlOnMachineDatabase",
        }
        findings, counts = live._normalize_findings(
            [record], "defender_recommendations", self.inventory, SUB, REFERENCE
        )
        self.assertEqual(findings, [])
        self.assertEqual(counts["arc_matched_records"], 0)
        self.assertEqual(counts["excluded_sql_descendant_records"], 1)

    def test_sql_subassessment_types_are_excluded_even_if_additional_data_contains_arc_id(self):
        record = assessment()
        record["properties"]["additionalData"] = {"assessedResourceType": "SqlDatabaseVulnerabilityAssessment"}
        findings, counts = live._normalize_findings(
            [record], "defender_vulnerabilities", self.inventory, SUB, REFERENCE
        )
        self.assertEqual(findings, [])
        self.assertEqual(counts["excluded_sql_descendant_records"], 1)


class LiveFlowTests(unittest.TestCase):
    def setUp(self):
        LabRouter.fail_source = None
        LabRouter.fail_extension = False
        LabRouter.calls = []
        self.patches = [
            patch.object(live, "SUBSCRIPTION_ID", SUB), patch.object(live, "TENANT_ID", TENANT),
            patch.object(live, "MANAGED_IDENTITY_CLIENT_ID", CLIENT_ID),
            patch.object(live, "_get_token", return_value="DO_NOT_EXPORT_ACCESS_TOKEN"),
            patch.object(live, "ArmClient", LabRouter),
            patch.object(live, "_utc_now", return_value=REFERENCE),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def snapshot(self):
        return live._collect_live(live._validate_config(), REFERENCE)

    def test_live_flow_paginates_and_preserves_health_plan_and_location_boundaries(self):
        result = live.main(operation="query", limit=100)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["total_matched"], 2)
        self.assertGreaterEqual(result["returned"], 1)
        self.assertLessEqual(result["returned"], 2)
        self.assertEqual(result["has_more"], result["returned"] < 2)
        self.assertEqual(result["summary"]["servers_p2"], 2)
        self.assertEqual(result["summary"]["sensor_verified_healthy"], 0)
        self.assertEqual(result["summary"]["by_provider"], {"unknown": 2})
        snapshot = self.snapshot()
        by_name = {r["server_name"]: r for r in snapshot["inventory"]}
        self.assertEqual(by_name["Alpha"]["mde_extension"], "Succeeded")
        self.assertEqual(by_name["Alpha"]["sensor_health"], "Unknown")
        self.assertEqual(by_name["Beta"]["connectivity"], "Expired")
        self.assertEqual(by_name["Beta"]["mde_extension"], "Failed")
        self.assertTrue(by_name["Beta"]["plan_inherited"])
        self.assertEqual(result["summary"]["source_observed_actionable_findings"]["Vulnerability"], 0)
        self.assertEqual(result["summary"]["source_observed_actionable_findings"]["Alert"], 0)
        sources = {s["name"]: s for s in snapshot["sources"]}
        self.assertEqual(sources["defender_recommendations"]["pages"], 2)
        self.assertEqual(result["sources"]["mde_sensor_health"], "unavailable")
        self.assertFalse(result["coverage"]["subscription_secure_score_collected"])
        encoded = json.dumps(result)
        self.assertNotIn("DO_NOT_EXPORT", encoded)
        self.assertEqual(live.main(operation="query", mde="healthy")["total_matched"], 0)

    def test_failed_optional_finding_source_is_null_and_partial_not_zero(self):
        LabRouter.fail_source = "defender_vulnerabilities"
        snapshot = self.snapshot()
        self.assertEqual(snapshot["status"], "partial")
        self.assertIsNone(snapshot["summary"]["source_observed_actionable_findings"]["Vulnerability"])
        source = next(s for s in snapshot["sources"] if s["name"] == "defender_vulnerabilities")
        self.assertEqual(source["status"], "unavailable")
        self.assertEqual(source["errors"][0]["http_status"], 403)

    def test_failed_extension_source_is_unknown_never_missing(self):
        LabRouter.fail_extension = True
        snapshot = self.snapshot()
        beta = next(r for r in snapshot["inventory"] if r["server_name"] == "Beta")
        self.assertEqual(beta["mde_extension"], "Unknown")
        source = next(s for s in snapshot["sources"] if s["name"] == "arc_extensions")
        self.assertEqual(source["status"], "partial")
        self.assertEqual(source["resources_available"], 1)

    def test_essential_inventory_failure_returns_error_without_artifacts(self):
        LabRouter.fail_source = "arc_inventory"
        with tempfile.TemporaryDirectory() as folder, patch.object(live.Path, "cwd", return_value=Path(folder)):
            result = live.main()
            self.assertEqual(result["status"], "error")
            self.assertNotIn("report_path", result)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_tenant_or_resource_scope_mismatch_fails_closed(self):
        with patch.object(live, "TENANT_ID", CLIENT_ID):
            result = live.main(operation="query")
            self.assertEqual(result["error"]["code"], "scope_mismatch")
        with self.assertRaises(live.EvidenceError):
            live._inventory_row(machine(ARC_ALPHA.replace(SUB, TENANT)), SUB, REFERENCE)

    def test_query_does_not_write_reports(self):
        with patch.object(live, "_write_report") as writer:
            live.main(operation="query", mde="failed-extension")
            writer.assert_not_called()

    def test_error_samples_disclose_their_cap(self):
        errors = [{"message": f"error-{i}"} for i in range(10)]
        summaries = live._source_summaries([{
            "name": "test", "status": "partial", "errors": errors,
        }])
        self.assertEqual(summaries[0]["errors_total"], 10)
        self.assertEqual(summaries[0]["errors_returned"], 3)
        self.assertTrue(summaries[0]["errors_has_more"])


class HttpBoundaryTests(unittest.TestCase):
    def mock_requests(self, responses=None, exception=None):
        module = types.ModuleType("requests")

        class RequestException(Exception):
            pass

        class Session:
            def __init__(self):
                self.headers = {}
                self.calls = []
                self.responses = list(responses or [])

            def close(self):
                pass

            def request(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                if exception:
                    raise RequestException("DO_NOT_EXPORT_TOKEN_FROM_EXCEPTION")
                return self.responses.pop(0)

        module.RequestException = RequestException
        module.Session = Session
        return module

    def test_redirects_and_untrusted_hosts_never_receive_a_second_request(self):
        response = types.SimpleNamespace(status_code=302, headers={"Location": "https://evil.example"})
        module = self.mock_requests([response])
        with patch.dict(sys.modules, {"requests": module}):
            client = live.ArmClient("TOKEN")
            with self.assertRaises(live.EvidenceError):
                client.request("GET", live.ARM_ORIGIN + "/subscriptions/" + SUB, "test")
            self.assertEqual(len(client.session.calls), 1)
            self.assertFalse(client.session.calls[0][1]["allow_redirects"])
            for url in ("http://management.azure.com", "https://evil.example", "https://user@management.azure.com"):
                with self.assertRaises(live.EvidenceError):
                    client.request("GET", url, "test")
            self.assertEqual(len(client.session.calls), 1)

    def test_http_transport_error_is_sanitized_and_write_methods_rejected(self):
        module = self.mock_requests(exception=True)
        with patch.dict(sys.modules, {"requests": module}):
            client = live.ArmClient("TOKEN")
            with self.assertRaises(live.EvidenceError) as raised:
                client.request("GET", live.ARM_ORIGIN + "/subscriptions/" + SUB, "test")
            self.assertNotIn("DO_NOT_EXPORT", raised.exception.message)
            for method in ("PUT", "PATCH", "DELETE"):
                with self.assertRaises(live.EvidenceError):
                    client.request(method, live.ARM_ORIGIN + "/subscriptions/" + SUB, "test")
            with self.assertRaises(live.EvidenceError):
                client.request("POST", live.ARM_ORIGIN + "/subscriptions/" + SUB, "test", {})

    def test_transient_retry_is_bounded_and_never_returns_error_body(self):
        responses = [
            types.SimpleNamespace(status_code=429, headers={"Retry-After": "2"}),
            types.SimpleNamespace(status_code=200, headers={}, json=lambda: {"value": []}),
        ]
        module = self.mock_requests(responses)
        with patch.dict(sys.modules, {"requests": module}), patch.object(live.time, "sleep") as sleep:
            client = live.ArmClient("TOKEN")
            self.assertEqual(client.request("GET", live.ARM_ORIGIN + "/subscriptions/" + SUB, "test"), {"value": []})
            sleep.assert_called_once_with(2)
            self.assertEqual(len(client.session.calls), 2)

    def test_invalid_json_and_non_object_responses_are_unavailable(self):
        def bad_json():
            raise ValueError("DO_NOT_EXPORT_RAW_BODY")

        for response_json in (bad_json, lambda: []):
            response = types.SimpleNamespace(status_code=200, headers={}, json=response_json)
            module = self.mock_requests([response])
            with patch.dict(sys.modules, {"requests": module}):
                client = live.ArmClient("TOKEN")
                with self.assertRaises(live.EvidenceError) as raised:
                    client.request("GET", live.ARM_ORIGIN + "/subscriptions/" + SUB, "test")
                self.assertNotIn("DO_NOT_EXPORT", raised.exception.message)


class SimulationTests(unittest.TestCase):
    def test_exact_200_server_fixture_and_requested_distributions(self):
        snapshot = sim._fixture(REFERENCE)
        self.assertEqual(snapshot["status"], "success")
        self.assertEqual(snapshot["provenance"], "SIMULATED")
        self.assertEqual(snapshot["summary"]["servers"], 200)
        self.assertEqual(snapshot["summary"]["by_provider"], {"gcp": 58, "onprem": 142})
        self.assertEqual(snapshot["summary"]["by_environment"], {
            "Production": 90, "Preproduction": 50, "Dev": 35, "DMZ": 17, "Backup": 8,
        })
        self.assertEqual(snapshot["summary"]["by_os"], sim.DEMO_OS_COUNTS)
        for environment, _, onprem, gcp in sim.DEMO_LAYOUT:
            hosts = [r for r in snapshot["inventory"] if r["environment"] == environment]
            self.assertEqual(Counter(r["provider"] for r in hosts), {"onprem": onprem, **({"gcp": gcp} if gcp else {})})
        self.assertEqual(len({r["resource_id"] for r in snapshot["inventory"]}), 200)
        self.assertTrue(all(r["provenance"] == "SIMULATED" for r in snapshot["inventory"] + snapshot["findings"]))

    def test_fixture_is_deterministic_and_does_not_invent_cves(self):
        self.assertEqual(sim._fixture(REFERENCE), sim._fixture(REFERENCE))
        fixture = sim._fixture(REFERENCE)
        for finding in fixture["findings"]:
            self.assertTrue(finding["finding_id"].startswith(("DEMO-VA-", "DEMO-REC-", "DEMO-ALERT-", "DEMO-BASELINE-")))
        self.assertNotRegex(json.dumps(fixture), r"CVE-\d{4}-\d+")
        self.assertTrue(any(f["provider"] == "gcp" for f in fixture["findings"]))

    def test_offline_simulation_never_acquires_tokens_or_networks(self):
        tree = ast.parse((SCENARIO / "simulate-arc-defender-mercadona.py").read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add((node.module or "").split(".")[0])
        self.assertFalse(imports & {"requests", "azure", "socket", "urllib", "http"})
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            result = sim.main(operation="query", provider="gcp", limit=100)
        self.assertEqual(result["provenance"], "SIMULATED")
        self.assertFalse(result["scope"]["azure_called"])
        self.assertFalse(result["scope"]["token_acquired"])

    def test_query_caps_are_explicit_and_paging_is_deterministic(self):
        with patch.object(sim, "_utc_now", return_value=REFERENCE):
            first = sim.main(operation="query", provider="gcp", limit=10)
            second = sim.main(operation="query", provider="gcp", limit=10, offset=first["next_offset"])
            rows = []
            offset = 0
            while True:
                page = sim.main(operation="query", provider="gcp", limit=100, offset=offset)
                rows.extend(page["items"])
                if not page["has_more"]:
                    break
                self.assertGreater(page["next_offset"], offset)
                offset = page["next_offset"]
        self.assertEqual(first["total_matched"], 58)
        self.assertTrue(first["has_more"])
        self.assertLessEqual(first["returned"], 10)
        self.assertTrue(first["transport_capped"])
        self.assertEqual(second["items"], rows[first["returned"]:first["returned"] + second["returned"]])
        self.assertEqual(len(rows), 58)
        self.assertEqual(len({row["resource_id"] for row in rows}), 58)
        self.assertEqual(first["summary_scope"], "unfiltered_snapshot")
        self.assertEqual(sim.main(operation="query", offset=50000)["returned"], 0)
        self.assertFalse(sim.main(operation="query", offset=50000)["has_more"])

    def test_all_filter_dimensions_and_views(self):
        fixture = sim._fixture(REFERENCE)
        for name, value in (
            ("provider", "gcp"), ("environment", "Production"), ("resource_group", "DEMO-PRD-gcp"),
            ("server_name", "gcp"), ("connectivity", "Expired"), ("mde", "failed-extension"),
            ("mde", "missing-extension"), ("mde", "unverified"), ("mde", "healthy"), ("mde", "unhealthy"),
        ):
            params = parameters(**{name: value}, limit=100)
            result = sim._query(fixture, params)
            expected = [r for r in fixture["inventory"] if sim._matches(r, params)]
            self.assertEqual(result["total_matched"], len(expected))
        findings = sim.main(operation="query", view="findings", provider="gcp", severity="High", limit=100)
        self.assertGreater(findings["returned"], 0)
        fixture_ids = {r["resource_id"] for r in fixture["inventory"] if r["provider"] == "gcp"}
        self.assertTrue(all(
            f["resource_id"] in fixture_ids and f["technical_severity"] == "High" for f in findings["items"]
        ))
        actions = sim.main(operation="query", view="actions", limit=3)
        self.assertEqual(actions["returned"], 3)
        self.assertTrue(actions["has_more"])
        self.assertTrue(all(a["provenance"] == "SIMULATED" for a in actions["items"]))
        self.assertEqual(sim.main(operation="query", view="actions", provider="azure")["total_matched"], 0)

    def test_stale_simulated_hosts_do_not_have_verified_healthy_sensors(self):
        fixture = sim._fixture(REFERENCE)
        self.assertTrue(all(
            r["sensor_health"] == "Unknown" for r in fixture["inventory"] if r["connectivity"] != "Connected"
        ))


class EncodingAndArtifactTests(unittest.TestCase):
    def test_csv_formula_neutralization_quoting_and_unicode(self):
        values = ['=1+1', ' +SUM(A1:A2)', '-cmd', '@formula', '\t=payload', 'quote,"line\nbreak', "Espa\u00f1a"]
        document = sim._csv_document([{"value": v} for v in values], ["value"])
        parsed = list(csv.reader(io.StringIO(document)))
        self.assertEqual(parsed[0], ["value"])
        for index, value in enumerate(values[:5], 1):
            self.assertEqual(parsed[index][0], "'" + value)
        self.assertEqual(parsed[6][0], values[5])
        self.assertEqual(parsed[7][0], values[6])

    def test_html_script_json_and_attribute_injection_are_encoded(self):
        snapshot = sim._fixture(REFERENCE)
        dangerous = '</script><img src=x onerror="alert(1)"> & \u2028 \u2029'
        snapshot["inventory"][0]["server_name"] = dangerous
        snapshot["findings"][0]["title"] = dangerous
        document = sim._render_html(snapshot)
        self.assertNotIn(dangerous, document)
        self.assertIn("textElement", document)
        self.assertIn("\\u003c/script\\u003e", document)
        self.assertIn("connect-src 'none'", document)
        self.assertNotIn("innerHTML", document)
        data = document.split('<script type="application/json" id="report-data">', 1)[1].split("</script>", 1)[0]
        self.assertEqual(sim._unpack_snapshot(json.loads(data))["inventory"][0]["server_name"], dangerous)

    def test_self_contained_approved_logo_short_source_lines_and_renderer_parity(self):
        self.assertTrue(base64.b64decode(live.LOGO_BASE64, validate=True).startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(live.LOGO_BASE64, sim.LOGO_BASE64)
        regions = []
        for filename in ("generate-defender-cloud-report.py", "simulate-arc-defender-mercadona.py"):
            source = (SCENARIO / filename).read_text(encoding="utf-8")
            self.assertLess(max(map(len, source.splitlines())), 1000)
            regions.append(source.split("# BEGIN STANDALONE REPORT HELPERS", 1)[1]
                           .split("# END STANDALONE REPORT HELPERS", 1)[0])
        self.assertEqual(regions[0], regions[1])
        document = sim._render_html(sim._fixture(REFERENCE))
        self.assertIn("linear-gradient(120deg,#0a3022", document)
        self.assertIn('"Palatino Linotype",Georgia,serif', document)
        self.assertIn('alt="Mercadona"', document)
        self.assertIn("SIMULATED DEMO", document)
        self.assertIn('label for="search"', document)
        self.assertIn("aria-sort", document)

    def test_report_outputs_all_artifacts_without_large_inventory_in_tool_response(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(sim.Path, "cwd", return_value=Path(folder)):
            result = sim.main()
            self.assertEqual(result["status"], "success")
            self.assertNotIn("inventory", result)
            for key in ("report_path", "csv_path", "findings_csv_path", "snapshot_path"):
                self.assertTrue(Path(result[key]).is_file())
            snapshot = json.loads(Path(result["snapshot_path"]).read_text(encoding="utf-8"))
            self.assertEqual(len(snapshot["inventory"]), 200)
            csv_rows = list(csv.DictReader(io.StringIO(Path(result["csv_path"]).read_text(encoding="utf-8-sig"))))
            self.assertEqual(len(csv_rows), 200)
            self.assertTrue(all(r["provenance"] == "SIMULATED" for r in csv_rows))
            finding_rows = list(csv.DictReader(io.StringIO(
                Path(result["findings_csv_path"]).read_text(encoding="utf-8-sig")
            )))
            self.assertTrue(all(r["provenance"] == "SIMULATED" for r in finding_rows))
            self.assertEqual(result["summary"]["by_provider"], {"gcp": 58, "onprem": 142})
            self.assertEqual(len(list((Path(folder) / "arc-defender-reports").iterdir())), 4)

    def test_storage_failure_returns_error_and_no_success_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            occupied = Path(folder) / "arc-defender-reports"
            occupied.write_text("occupied", encoding="utf-8")
            with patch.object(sim.Path, "cwd", return_value=Path(folder)):
                result = sim.main()
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error"]["code"], "artifact_write_failed")
            self.assertNotIn("report_path", result)

    def test_json_export_is_lossless_and_does_not_include_raw_live_properties(self):
        LabRouter.fail_source = None
        LabRouter.fail_extension = False
        config = {"SUBSCRIPTION_ID": SUB, "TENANT_ID": TENANT, "MANAGED_IDENTITY_CLIENT_ID": CLIENT_ID}
        with patch.object(live, "_get_token", return_value="DO_NOT_EXPORT_ACCESS_TOKEN"):
            with patch.object(live, "ArmClient", LabRouter):
                snapshot = live._collect_live(config, REFERENCE)
        encoded = json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
        self.assertNotIn("DO_NOT_EXPORT", encoded)
        self.assertNotIn("protectedSettings", encoded)
        self.assertNotIn("instanceView", encoded)
        self.assertEqual(json.loads(encoded), snapshot)

    def test_unavailable_source_record_count_is_visible_as_unknown(self):
        snapshot = sim._fixture(REFERENCE)
        snapshot["sources"][0].update({"status": "unavailable", "records": None})
        document = sim._render_html(snapshot)
        self.assertIn("unavailable</span></td><td>Unknown</td>", document)

    def test_parameter_schema_matches_main_defaults_and_unknown_inputs_are_disabled(self):
        import inspect

        schema = json.loads((SCENARIO / "tool-parameters.schema.json").read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        for module in (live, sim):
            signature = inspect.signature(module.main)
            self.assertEqual(set(schema["properties"]), set(signature.parameters))
            for name, parameter in signature.parameters.items():
                self.assertEqual(schema["properties"][name]["default"], parameter.default)


class TransportBudgetTests(unittest.TestCase):
    def assert_budget(self, result):
        self.assertLessEqual(len(json.dumps(result).encode("utf-8")), 3500)
        self.assertEqual(json.loads(json.dumps(result)), result)

    def test_report_responses_fit_default_serializer_and_preserve_complete_artifacts(self):
        LabRouter.fail_source = None
        LabRouter.fail_extension = False
        for module in (sim, live):
            with tempfile.TemporaryDirectory() as folder:
                patches = [patch.object(module.Path, "cwd", return_value=Path(folder))]
                if module is live:
                    patches += [
                        patch.object(live, "SUBSCRIPTION_ID", SUB), patch.object(live, "TENANT_ID", TENANT),
                        patch.object(live, "MANAGED_IDENTITY_CLIENT_ID", CLIENT_ID),
                        patch.object(live, "_get_token", return_value="MOCK"),
                        patch.object(live, "ArmClient", LabRouter),
                    ]
                for item in patches:
                    item.start()
                try:
                    result = module.main(operation="report")
                finally:
                    for item in reversed(patches):
                        item.stop()
                self.assertNotEqual(result["status"], "error")
                self.assert_budget(result)
                for key in ("report_path", "csv_path", "findings_csv_path", "snapshot_path"):
                    self.assertTrue(Path(result[key]).is_file())
                snapshot = json.loads(Path(result["snapshot_path"]).read_text(encoding="utf-8"))
                self.assertEqual(len(snapshot["inventory"]), 200 if module is sim else 2)
                self.assertEqual(len(result["top_actions"]), 3)
                self.assertIn("qualification", result)
                self.assertIn("unknown_sources", result["coverage"])
                self.assertIn("arc_inventory", result["sources"])

    def test_all_query_views_max_requested_limits_filters_and_errors_fit(self):
        fixture = sim._fixture(REFERENCE)
        configurations = [
            {}, {"provider": "gcp"}, {"environment": "Production"},
            {"connectivity": "Expired"}, {"mde": "missing-extension"},
            {"mde": "unverified"}, {"severity": "High"}, {"server_name": "no-match"},
            {"resource_group": "DEMO-PRD-gcp"}, {"provider": "azure"},
        ]
        for view in ("inventory", "findings", "actions"):
            for filters in configurations:
                with self.subTest(view=view, filters=filters):
                    result = sim._query(fixture, parameters(view=view, limit=100, **filters))
                    self.assert_budget(result)
                    self.assertEqual(result["returned"], len(result["items"]))
                    self.assertEqual(result["requested_limit"], 100)
                    self.assertEqual(result["has_more"], result["returned"] < result["total_matched"])
                    if result["has_more"]:
                        self.assertGreater(result["next_offset"], 0)
        self.assert_budget(sim.main(limit=101))
        self.assert_budget(live.main())

    def test_live_query_views_and_partial_source_error_envelopes_fit(self):
        LabRouter.fail_source = "defender_vulnerabilities"
        LabRouter.fail_extension = True
        config = {"SUBSCRIPTION_ID": SUB, "TENANT_ID": TENANT, "MANAGED_IDENTITY_CLIENT_ID": CLIENT_ID}
        with patch.object(live, "_get_token", return_value="MOCK"), patch.object(live, "ArmClient", LabRouter):
            snapshot = live._collect_live(config, REFERENCE)
        for view in ("inventory", "findings", "actions"):
            result = live._query(snapshot, parameters(live, view=view, limit=100))
            self.assert_budget(result)
            self.assertEqual(result["status"], "partial")
            self.assertGreaterEqual(result["source_errors"]["total"], 1)
            self.assertEqual(result["source_errors"]["returned"], 1)
            self.assertIsNone(result["summary"]["source_observed_actionable_findings"]["Vulnerability"])
        LabRouter.fail_source = None
        LabRouter.fail_extension = False

    def test_unicode_escaping_counts_against_budget_and_full_snapshot_is_unchanged(self):
        snapshot = sim._fixture(REFERENCE)
        for index, row in enumerate(snapshot["inventory"]):
            row["server_name"] = "\u00f1" * 70 + str(index)
            row["os"] = "\u4e2d" * 80
        original = json.dumps(snapshot)
        result = sim._query(snapshot, parameters(limit=100))
        self.assert_budget(result)
        self.assertTrue(result["transport_capped"])
        self.assertGreater(result["returned"], 0)
        self.assertLess(result["returned"], 100)
        self.assertEqual(json.dumps(snapshot), original)
        self.assertEqual(result["total_matched"], 200)

    def test_single_oversized_row_fails_explicitly_instead_of_zero_row_infinite_cursor(self):
        snapshot = sim._fixture(REFERENCE)
        for row in snapshot["inventory"]:
            row["server_name"] = "\u4e2d" * 2000
        with patch.object(sim, "_fixture", return_value=snapshot):
            result = sim.main(operation="query")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "query_item_exceeds_budget")
        self.assert_budget(result)
        self.assertNotIn("next_offset", result)

    def test_source_error_sample_cap_is_disclosed_without_bloating_response(self):
        snapshot = sim._fixture(REFERENCE)
        snapshot["sources"][0].update({
            "status": "partial", "records": None,
            "errors": [{"code": "api_failed", "message": "private detail", "http_status": 403}] * 1000,
        })
        result = sim._query(snapshot, parameters(limit=1))
        self.assert_budget(result)
        self.assertEqual(result["source_errors"]["total"], 1000)
        self.assertEqual(result["source_errors"]["returned"], 1)
        self.assertTrue(result["source_errors"]["has_more"])
        self.assertNotIn("private detail", json.dumps(result))

    def test_realistic_long_runtime_root_paths_keep_report_json_within_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "root" / "sreagent" / "terminalRoot" / "tmp" / "ThreadFiles" / SUB
            root.mkdir(parents=True)
            LabRouter.fail_source = None
            LabRouter.fail_extension = False
            for module in (sim, live):
                patches = [patch.object(module.Path, "cwd", return_value=root)]
                if module is live:
                    patches += [
                        patch.object(live, "SUBSCRIPTION_ID", SUB), patch.object(live, "TENANT_ID", TENANT),
                        patch.object(live, "MANAGED_IDENTITY_CLIENT_ID", CLIENT_ID),
                        patch.object(live, "_get_token", return_value="MOCK"),
                        patch.object(live, "ArmClient", LabRouter),
                    ]
                for item in patches:
                    item.start()
                try:
                    result = module.main(operation="report")
                finally:
                    for item in reversed(patches):
                        item.stop()
                self.assertNotEqual(result["status"], "error")
                self.assert_budget(result)
                for key in ("report_path", "csv_path", "findings_csv_path", "snapshot_path"):
                    path = Path(result[key])
                    self.assertTrue(path.is_relative_to(root.resolve()))
                    self.assertEqual(path.parent.name, "arc-defender-reports")
                    self.assertTrue(path.is_file())
                snapshot = json.loads(Path(result["snapshot_path"]).read_text(encoding="utf-8"))
                self.assertEqual(len(snapshot["inventory"]), 200 if module is sim else 2)


class ArtifactRootTests(unittest.TestCase):
    def test_fixed_subdirectory_is_resolved_under_runtime_cwd(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(sim.Path, "cwd", return_value=Path(folder)):
            root, directory = sim._artifact_directory()
            self.assertEqual(root, Path(folder).resolve())
            self.assertEqual(directory, root / "arc-defender-reports")
            self.assertTrue(directory.is_relative_to(root))
            self.assertFalse(directory.exists())

    def test_filesystem_root_is_rejected_before_writing(self):
        root = Path(Path.cwd().anchor)
        with patch.object(sim.Path, "cwd", return_value=root):
            result = sim.main(operation="report")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "unsafe_artifact_root")
        self.assertNotIn("report_path", result)

    def test_absolute_or_parent_traversal_output_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(sim.Path, "cwd", return_value=Path(folder)):
            for directory in (Path(folder), Path(".."), Path("../elsewhere"), Path(".")):
                with self.subTest(directory=directory), patch.object(sim, "OUTPUT_DIRECTORY", directory):
                    result = sim.main(operation="report")
                    self.assertEqual(result["status"], "error")
                    self.assertEqual(result["error"]["code"], "unsafe_artifact_directory")
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_symlink_resolution_escape_is_rejected_without_following_for_writes(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside:
            root, target = Path(folder).resolve(), Path(outside).resolve()
            original = sim.Path.resolve

            def resolver(path, *args, **kwargs):
                if path == root / "arc-defender-reports":
                    return target.resolve()
                return original(path, *args, **kwargs)

            with patch.object(sim.Path, "cwd", return_value=root), patch.object(sim.Path, "resolve", resolver):
                result = sim.main(operation="report")
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error"]["code"], "unsafe_artifact_directory")
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(list(root.iterdir()), [])

    def test_directory_scope_is_rechecked_after_creation(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside:
            root, target = Path(folder).resolve(), Path(outside).resolve()
            original = sim.Path.resolve
            calls = 0

            def resolver(path, *args, **kwargs):
                nonlocal calls
                if path == root / "arc-defender-reports":
                    calls += 1
                    return original(path, *args, **kwargs) if calls == 1 else target.resolve()
                return original(path, *args, **kwargs)

            with patch.object(sim.Path, "cwd", return_value=root), patch.object(sim.Path, "resolve", resolver):
                result = sim.main(operation="report")
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error"]["code"], "unsafe_artifact_directory")
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(list((root / "arc-defender-reports").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
