"""SIMULATED Arc administration evidence; all readers are mocked, never live."""

import copy
import csv
import importlib.util
import io
import json
import re
import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import test_infrastructure_operations as existing
from test_infrastructure_operations import (
    ARC_ID, CLIENT, REFERENCE, SUBSCRIPTION, TENANT, VM_ID, WORKSPACE,
    inventory, parameters, tool,
)


def machine_row(**properties):
    return {
        "id": ARC_ID, "name": "test-arc", "type": "microsoft.hybridcompute/machines",
        "resourceGroup": "test-rg", "location": "test-region", "tags": {},
        "properties": {
            "status": "Connected", "lastStatusChange": "2026-10-08T15:00:00Z",
            "agentVersion": "1.9.300.0", "osName": "Synthetic Linux",
            "osType": "Linux", "osSku": "Synthetic Linux 1",
            "osVersion": "1.0", **properties,
        },
    }


def extension_row(name="synthetic-monitor", **properties):
    return {
        "id": ARC_ID + "/extensions/" + name, "name": name,
        "type": "microsoft.hybridcompute/machines/extensions",
        "location": "test-region",
        "properties": {
            "publisher": "Synthetic.Publisher", "type": "SyntheticMonitor",
            "typeHandlerVersion": "1.10", "provisioningState": "Succeeded",
            "enableAutomaticUpgrade": True, "autoUpgradeMinorVersion": False,
            "instanceView": {"typeHandlerVersion": "1.9.1"},
            **properties,
        },
    }


def baseline(**overrides):
    return {
        "baseline_id": "synthetic-review-202610", "owner": "Synthetic owner",
        "reference": "SIMULATED approved change-review reference, not a support claim",
        "as_of_utc": "2026-10-01T00:00:00Z",
        "valid_until_utc": "2026-10-31T00:00:00Z",
        "os_type": "Linux", "os_sku": "Synthetic Linux 1",
        "os_version": "1.0", "location": "test-region",
        "agent_review_version": "1.10",
        "notes": "SIMULATED review target; installation suitability is not established.",
        "required_extensions": [{
            "publisher": "Synthetic.Publisher", "type": "SyntheticMonitor",
            "review_version": "1.10", "enable_automatic_upgrade": True,
        }],
        **overrides,
    }


def config(baselines=None):
    with patch.object(tool, "ARC_ADMIN_BASELINES", [] if baselines is None else baselines):
        rules = tool._arc_baselines()
    return {"subscription_id": SUBSCRIPTION, "tenant_id": TENANT, "client_id": CLIENT,
            "workspace_ids": [WORKSPACE], "arc_baselines": rules}


def page(rows, total=None, token=None, **overrides):
    result = {"data": rows, "count": len(rows), "totalRecords": len(rows) if total is None else total,
              "resultTruncated": "true" if token is not None else "false"}
    if token is not None:
        result["$skipToken"] = token
    return {**result, **overrides}


class ExtensionClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def request(self, method, url, source, body=None, deadline=None):
        tool._validate_endpoint(method, url, body, config())
        self.calls.append((method, url, source, copy.deepcopy(body), deadline))
        reply = next(self.replies)
        if isinstance(reply, tool.EvidenceError):
            raise reply
        return reply


def simulated_snapshot(baselines=None, rows=None, source_status="complete", properties=None, reference=REFERENCE):
    resources = tool._normalize_resources([machine_row(**(properties or {}))], SUBSCRIPTION)
    extensions = tool._normalize_arc_extensions(
        [extension_row()] if rows is None else rows, resources, SUBSCRIPTION, reference,
    )
    sources = [tool._source("inventory", "complete", reference, 1),
               tool._source("arc_extensions", source_status, reference, len(extensions),
                            pages=1, subscription_rows_read=len(extensions),
                            declared_subscription_rows=len(extensions) if source_status == "complete" else None)]
    data = tool._finish_snapshot(resources, [], sources, [], {}, [], [], config(baselines),
                                 parameters(reference=reference), reference, 1, extensions)
    data["provenance"] = "SIMULATED"
    return data


class MissingAdministrationRegressionTests(unittest.TestCase):
    def test_inventory_retains_native_agent_and_os_metadata(self):
        resource = tool._normalize_resources([machine_row()], SUBSCRIPTION)[0]
        self.assertEqual(resource.get("arc_agent_version"), "1.9.300.0")
        self.assertEqual(resource.get("os_type"), "Linux")
        self.assertEqual(resource.get("os_sku"), "Synthetic Linux 1")
        self.assertEqual(resource.get("os_version"), "1.0")

    def test_native_extension_metadata_is_normalized_without_private_settings(self):
        row = extension_row(settings={"secret": "DO-NOT-EXPORT"},
                            protectedSettings={"secret": "DO-NOT-EXPORT"},
                            instanceView={"typeHandlerVersion": "1.9.1",
                                          "status": {"message": "DO-NOT-EXPORT"}})
        resources = tool._normalize_resources([machine_row()], SUBSCRIPTION)
        result = tool._normalize_arc_extensions([row], resources, SUBSCRIPTION, REFERENCE)
        self.assertEqual(result[0]["extension_id"], row["id"])
        self.assertEqual(result[0]["instance_view_version"], "1.9.1")
        self.assertNotIn("DO-NOT-EXPORT", json.dumps(result))

    def test_numeric_version_order_is_not_lexicographic(self):
        self.assertEqual(tool._compare_versions("1.9.300.0", "1.10"), -1)
        self.assertEqual(tool._compare_versions("1.10", "1.10.0.0"), 0)
        self.assertIsNone(tool._compare_versions("1.10-preview", "1.10"))

    def test_extensions_are_an_explicit_paged_query_not_extra_machines(self):
        self.assertEqual(parameters(view="extensions")["view"], "extensions")


class ArcBaselineTests(unittest.TestCase):
    def test_default_is_empty_and_invalid_configuration_stops_before_authentication(self):
        self.assertEqual(config()["arc_baselines"], [])
        invalid = baseline(valid_until_utc="2027-01-01T00:00:00Z")
        with patch.object(tool, "SUBSCRIPTION_ID", SUBSCRIPTION), patch.object(tool, "TENANT_ID", TENANT), \
             patch.object(tool, "MANAGED_IDENTITY_CLIENT_ID", CLIENT), \
             patch.object(tool, "ARC_ADMIN_BASELINES", [invalid]), patch.object(tool, "AzureReadClient") as client:
            response = tool.main(operation="query")
        self.assertEqual(response["error"]["code"], "configuration_required")
        client.assert_not_called()

    def test_exact_numeric_comparisons_and_non_comparable_versions(self):
        cases = (
            ("1.9", "1.10", -1), ("1.68.123.0", "1.68", 1), ("1.10", "1.10.0.0", 0),
            ("01.010.0", "1.10", 0), ("2.0", "1.99.9999.1", 1),
            (None, "1.10", None), ("1.10-preview", "1.10", None), ("1", "1.10", None),
            ("1.2.3.4.5", "1.10", None), ("1.10.*", "1.10", None), ("1.10 ", "1.10", None),
        )
        for observed, target, expected in cases:
            with self.subTest(observed=observed):
                self.assertEqual(tool._compare_versions(observed, target), expected)

    def test_baseline_validation_rejects_unbounded_ambiguous_and_unowned_policies(self):
        variants = [
            baseline(owner=""), baseline(reference=""), baseline(os_type="*"), baseline(location=""),
            baseline(agent_review_version="latest"), baseline(agent_review_version="1.68-preview"),
            baseline(as_of_utc="2026-10-01"), baseline(valid_until_utc="2026-10-01T00:00:00Z"),
            baseline(valid_until_utc="2026-11-01T00:00:01Z"), baseline(settings={"value": "not allowed"}),
            baseline(required_extensions=[{"publisher": "P", "type": "T", "enable_automatic_upgrade": "true"}]),
            baseline(required_extensions=[{"publisher": "P", "type": "T", "settings": {}}]),
            baseline(required_extensions=[{"publisher": "P", "type": "T", "review_version": "newest"}]),
            baseline(required_extensions=[{"publisher": "P", "type": "T"}] * 2),
        ]
        for rule in variants:
            with self.subTest(rule=rule), patch.object(tool, "ARC_ADMIN_BASELINES", [rule]), self.assertRaises(tool.EvidenceError):
                tool._arc_baselines()
        for rules in ([baseline(), baseline(baseline_id="another")],
                      [baseline(), baseline(location="other")], [baseline()] * 51):
            with self.subTest(count=len(rules)), patch.object(tool, "ARC_ADMIN_BASELINES", rules), self.assertRaises(tool.EvidenceError):
                tool._arc_baselines()

    def test_dated_baseline_boundaries_keep_expired_or_future_targets_unknown(self):
        for reference, expected in (
            (tool._time("2026-10-01T00:00:00Z", "test"), "current"),
            (tool._time("2026-10-31T00:00:00Z", "test") - timedelta(seconds=1), "current"),
            (tool._time("2026-10-31T00:00:00Z", "test"), "stale"),
            (tool._time("2026-09-30T23:59:59Z", "test"), "not_yet_valid"),
        ):
            data = simulated_snapshot([baseline()], reference=reference)
            admin = data["resources"][0]["arc_administration"]
            with self.subTest(reference=reference):
                self.assertEqual(admin["baseline_status"], expected)
                self.assertEqual(data["arc_baselines"][0]["status"], expected)
                self.assertEqual(any(row["kind"] == "arc_agent_review" for row in data["signals"]), expected == "current")
                if expected != "current":
                    self.assertEqual(admin["agent_version_status"], "unknown")
                    self.assertFalse(any(row["kind"] in ("arc_required_extension", "arc_extension_review") for row in data["signals"]))

    def test_empty_unmatched_and_missing_version_never_prove_supported_or_healthy(self):
        for rules, props, expected in (
            ([], {}, "not_configured"),
            ([baseline(os_type="Windows")], {}, "not_matched"),
            ([baseline(os_sku="Different SKU")], {}, "not_matched"),
            ([baseline(location="other-region")], {}, "not_matched"),
            ([baseline()], {"agentVersion": None}, "current"),
            ([baseline()], {"agentVersion": "1.68-preview"}, "current"),
            ([baseline()], {"osName": "Windows Server 2008", "osSku": None}, "not_matched"),
        ):
            data = simulated_snapshot(rules, properties=props)
            admin = data["resources"][0]["arc_administration"]
            with self.subTest(rules=rules, props=props):
                self.assertEqual(admin["baseline_status"], expected)
                self.assertEqual(admin["agent_version_status"], "unknown")
                self.assertEqual(admin["agent_support_status"], "unknown")
                self.assertEqual(admin["os_support_status"], "unknown")
                self.assertFalse(any(row["kind"] == "arc_agent_review" for row in data["signals"]))

    def test_review_target_is_not_latest_support_or_a_write_instruction(self):
        data = simulated_snapshot([baseline()])
        admin = data["resources"][0]["arc_administration"]
        self.assertEqual(admin["agent_version_status"], "below_review_target")
        signal = next(row for row in data["signals"] if row["kind"] == "arc_agent_review")
        self.assertEqual(signal["evidence"]["reference"], baseline()["reference"])
        self.assertIn("not a latest-version", signal["details"])
        self.assertTrue(all(not row["automatic_action"] for row in data["actions"]))
        self.assertIn(signal["signal_id"], data["actions"][0]["evidence_signal_ids"])


class ArcExtensionSourceTests(unittest.TestCase):
    def collect(self, replies):
        client = ExtensionClient(replies)
        rows, receipt = tool._collect_arc_extensions(
            client, config(), tool._normalize_resources([machine_row()], SUBSCRIPTION), REFERENCE,
        )
        return client, rows, receipt

    def test_fixed_native_arg_projection_and_paged_metadata(self):
        other = extension_row("second", instanceView={"typeHandlerVersion": "1.10"})
        client, rows, receipt = self.collect([
            page([extension_row()], 2, "next"), page([other], 2),
        ])
        self.assertEqual(len(rows), 2)
        self.assertEqual(receipt["status"], "complete")
        self.assertEqual(receipt["pages"], 2)
        self.assertEqual(receipt["subscription_rows_read"], 2)
        self.assertEqual(receipt["declared_subscription_rows"], 2)
        self.assertEqual(client.calls[1][3]["options"]["$skipToken"], "next")
        query = client.calls[0][3]["query"]
        self.assertEqual(query, tool._arc_extension_query())
        self.assertNotIn("settings", query.casefold())
        self.assertNotIn("message", query.casefold())
        self.assertNotIn("status", query.casefold())
        self.assertTrue(all(call[0] == "POST" and call[4] is not None for call in client.calls))

    def test_valid_empty_and_denied_are_different_receipts(self):
        _, rows, receipt = self.collect([page([])])
        self.assertEqual(rows, [])
        self.assertEqual(receipt["status"], "complete")
        self.assertEqual(receipt["pages"], 1)
        self.assertEqual(receipt["declared_subscription_rows"], 0)
        _, rows, receipt = self.collect([tool.EvidenceError("api_failed", "SIMULATED denial.", "arc_extensions", 403)])
        self.assertEqual(rows, [])
        self.assertEqual(receipt["status"], "error")
        self.assertEqual(receipt["error"]["http_status"], 403)
        self.assertIsNone(receipt["declared_subscription_rows"])

    def test_later_page_failure_retains_complete_accepted_pages_and_marks_partial(self):
        _, rows, receipt = self.collect([
            page([extension_row()], 2, "next"),
            tool.EvidenceError("api_failed", "SIMULATED continuation failure.", "arc_extensions", 503),
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(receipt["status"], "partial")
        self.assertEqual(receipt["pages"], 1)
        self.assertEqual(receipt["declared_subscription_rows"], 2)
        self.assertEqual(receipt["error"]["http_status"], 503)

    def test_invalid_counts_empty_shapes_and_native_fields_are_errors(self):
        for reply in (
            {}, page([], count=True), page([], totalRecords=-1), page([], resultTruncated="unknown"),
            page([extension_row()], total=2), page([extension_row()], resultTruncated="true"),
            page([extension_row(enableAutomaticUpgrade="true")]),
            page([extension_row(publisher={"unsafe": "object"})]),
            page([extension_row(instanceView="invalid")]),
            page([{**extension_row(), "id": VM_ID + "/extensions/not-arc"}]),
            page([{**extension_row(), "id": ARC_ID.replace(SUBSCRIPTION, TENANT) + "/extensions/other"}]),
        ):
            with self.subTest(reply=reply):
                _, rows, receipt = self.collect([reply])
                self.assertEqual(rows, [])
                self.assertEqual(receipt["status"], "error")
                self.assertEqual(receipt["error"]["source"], "arc_extensions")

    def test_broken_continuations_never_become_complete(self):
        for second in (
            page([extension_row("second")], 3),
            page([extension_row()], 2),
            page([extension_row("second")], 3, "next"),
            page([], 2, "again"),
        ):
            with self.subTest(second=second):
                _, rows, receipt = self.collect([page([extension_row()], 2, "next"), second])
                self.assertEqual(receipt["status"], "partial")
                self.assertEqual(len(rows), 1)

    def test_exact_parent_join_never_uses_a_similar_hostname(self):
        other = extension_row()
        other["id"] = ARC_ID + "-other/extensions/synthetic-monitor"
        _, rows, receipt = self.collect([page([extension_row(), other])])
        self.assertEqual(len(rows), 1)
        self.assertEqual(receipt["subscription_rows_read"], 2)
        self.assertEqual(receipt["records"], 1)

    def test_page_row_and_time_caps_are_explicit_partial_not_healthy(self):
        first = page([extension_row()], 2, "next")
        with patch.object(tool, "MAX_ARC_EXTENSION_PAGES", 1):
            client, rows, receipt = self.collect([first])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(receipt["status"], "partial")
        self.assertEqual(len(rows), 1)
        with patch.object(tool, "MAX_ARC_EXTENSION_ROWS", 1):
            client, rows, receipt = self.collect([first])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(receipt["error"]["code"], "source_too_large")
        self.assertEqual(len(rows), 1)
        with patch.object(tool.time, "monotonic", side_effect=[0, 0, 0, 91]):
            client, rows, receipt = self.collect([first])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(receipt["error"]["code"], "source_budget_exceeded")
        self.assertEqual(receipt["status"], "partial")
        self.assertEqual(len(rows), 1)

    def test_new_endpoint_allowlist_cannot_become_arbitrary_queries_or_reads(self):
        url = tool.ARM_ORIGIN + "/providers/Microsoft.ResourceGraph/resources?api-version=" + tool.ARG_VERSION
        body = {"subscriptions": [SUBSCRIPTION], "query": tool._arc_extension_query(),
                "options": {"$top": 1000, "resultFormat": "objectArray"}}
        self.assertEqual(tool._validate_endpoint("POST", url, body, config()), tool.ARM_ORIGIN + "/.default")
        for bad_body in ({**body, "query": "resources | project properties.settings"},
                         {**body, "subscriptions": [TENANT]},
                         {**body, "options": {**body["options"], "$top": 5001}}):
            with self.subTest(body=bad_body), self.assertRaises(tool.EvidenceError):
                tool._validate_endpoint("POST", url, bad_body, config())
        for method, bad_url in (("GET", tool.ARM_ORIGIN + ARC_ID + "/extensions"),
                                ("PUT", tool.ARM_ORIGIN + ARC_ID),
                                ("POST", url + "&unapproved=true")):
            with self.subTest(url=bad_url), self.assertRaises(tool.EvidenceError):
                tool._validate_endpoint(method, bad_url, body, config())


class ArcAssessmentAndExportTests(unittest.TestCase):
    def test_requested_version_does_not_replace_missing_instance_view(self):
        data = simulated_snapshot([baseline()], rows=[extension_row(instanceView={})])
        extension = data["extensions"][0]
        self.assertEqual(extension["type_handler_version"], "1.10")
        self.assertIsNone(extension["instance_view_version"])
        self.assertEqual(extension["assessment"], "unknown")
        self.assertFalse(any(row["kind"] == "arc_extension_review" for row in data["signals"]))

    def test_auto_upgrade_missing_is_unknown_and_false_needs_an_explicit_rule(self):
        for policies, value, expected_review in (([], False, False), ([baseline()], False, True),
                                                 ([baseline()], None, False), ([baseline()], True, True)):
            rows = [extension_row(enableAutomaticUpgrade=value,
                                  instanceView={"typeHandlerVersion": "1.10" if value is not True else "1.9"})]
            data = simulated_snapshot(policies, rows=rows)
            with self.subTest(policies=bool(policies), value=value):
                self.assertIs(data["extensions"][0]["enable_automatic_upgrade"], value)
                self.assertEqual(any(row["kind"] == "arc_extension_review" for row in data["signals"]), expected_review)
                if value is None:
                    self.assertEqual(data["extensions"][0]["assessment"], "unknown")

    def test_native_failed_provisioning_is_review_even_without_policy_but_success_is_not_sensor_health(self):
        for state, review in (("Failed", True), ("Canceled", True), ("Creating", False), ("Succeeded", False), (None, False)):
            data = simulated_snapshot(rows=[extension_row(provisioningState=state)])
            with self.subTest(state=state):
                self.assertEqual(any(row["kind"] == "arc_extension_review" for row in data["signals"]), review)
                self.assertNotEqual(data["extensions"][0]["assessment"], "observed")

    def test_required_not_observed_is_qualified_and_never_inferred_from_partial_inventory(self):
        for status in ("complete", "partial", "error"):
            data = simulated_snapshot([baseline()], rows=[], source_status=status)
            required = [row for row in data["signals"] if row["kind"] == "arc_required_extension"]
            with self.subTest(status=status):
                self.assertEqual(bool(required), status == "complete")
                if required:
                    self.assertIn("visible inventory", required[0]["title"])
                    self.assertEqual(required[0]["evidence"]["permission_completeness"], "not_established")
                else:
                    self.assertIn("required_extension_presence_not_assessable", data["resources"][0]["arc_administration"]["unknowns"])

    def test_unidentifiable_extension_metadata_cannot_prove_required_extension_absence(self):
        data = simulated_snapshot([baseline()], rows=[extension_row(publisher=None, type=None)])
        self.assertFalse(any(row["kind"] == "arc_required_extension" for row in data["signals"]))
        self.assertIn("required_extension_presence_not_assessable", data["resources"][0]["arc_administration"]["unknowns"])

    def test_extension_version_never_ranks_other_publisher_type_or_location(self):
        for fields in ({"publisher": "Other.Publisher"}, {"type": "OtherType"}):
            data = simulated_snapshot([baseline()], rows=[extension_row(**fields)])
            self.assertFalse(any(row["kind"] == "arc_extension_review" for row in data["signals"]))
        row = {**extension_row(), "location": "different-region"}
        data = simulated_snapshot([baseline()], rows=[row])
        self.assertEqual(data["extensions"][0]["assessment"], "unknown")
        self.assertFalse(any(row["kind"] == "arc_extension_review" for row in data["signals"]))

    def test_status_change_connection_and_heartbeat_are_separate_clocks(self):
        data = simulated_snapshot(properties={"status": "Expired"})
        resource = data["resources"][0]
        self.assertEqual(resource["arc_status_changed_utc"], "2026-10-08T15:00:00Z")
        self.assertIsNone(resource["heartbeat"])
        signal = next(row for row in data["signals"] if row["kind"] == "arc_connection")
        self.assertEqual(signal["evidence"]["changed_utc"], resource["arc_status_changed_utc"])
        self.assertEqual(resource["arc_administration"]["os_support_status"], "unknown")
        with self.assertRaises(tool.EvidenceError):
            tool._normalize_resources([machine_row(lastStatusChange="not a date")], SUBSCRIPTION)

    def test_extension_queries_have_exact_totals_whole_rows_filters_and_no_machine_inflation(self):
        data = simulated_snapshot([baseline()], rows=[extension_row("extension-" + str(index)) for index in range(35)])
        self.assertEqual(data["summary"]["resources"], 1)
        self.assertEqual(data["summary"]["arc"], 1)
        self.assertEqual(data["summary"]["arc_extensions_observed"], 35)
        offset, ids = 0, []
        while True:
            response = tool._query(data, parameters(view="extensions", state="review", offset=offset, limit=100))
            self.assertEqual(response["provenance"], "SIMULATED")
            self.assertEqual(response["total_matched"], 35)
            self.assertLessEqual(len(json.dumps(response).encode("utf-8")), 3500)
            self.assertEqual(response["returned"], len(response["rows"]))
            ids.extend(row["extension_id"] for row in response["rows"])
            if not response["has_more"]:
                self.assertIsNone(response["next_offset"])
                break
            self.assertGreater(response["next_offset"], offset)
            offset = response["next_offset"]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 35)
        self.assertEqual(tool._query(data, parameters(view="extensions", state="observed"))["total_matched"], 0)
        self.assertEqual(tool._query(data, parameters(view="extensions", offset=50000))["returned"], 0)
        for overrides in ({"metric": "cpu_percent"}, {"severity": "warning"}):
            with self.subTest(overrides=overrides), self.assertRaises(tool.EvidenceError):
                parameters(view="extensions", **overrides)

    def test_empty_query_discloses_source_unavailability_instead_of_healthy_zero(self):
        data = simulated_snapshot(rows=[], source_status="error")
        data["sources"][1]["error"] = {"code": "api_failed", "source": "arc_extensions", "http_status": 403,
                                      "message": "SIMULATED denied read."}
        response = tool._query(data, parameters(view="extensions"))
        self.assertEqual(response["total_matched"], 0)
        self.assertEqual(response["extension_coverage"]["status"], "error")
        self.assertEqual(response["extension_coverage"]["error"]["http_status"], 403)
        self.assertIn("does not prove absence", response["extension_coverage"]["qualification"])

    def test_one_oversized_extension_row_is_an_error_not_a_skipped_cursor(self):
        row = extension_row(publisher="\u4e2d" * 256, type="\u4e2d" * 256)
        data = simulated_snapshot(rows=[row])
        with self.assertRaises(tool.EvidenceError) as caught:
            tool._query(data, parameters(view="extensions"))
        self.assertEqual(caught.exception.code, "query_row_too_large")

    def test_roundtrip_four_exports_csv_fields_and_html_keep_every_safe_record(self):
        data = simulated_snapshot([baseline()], rows=[extension_row("extension-" + str(index)) for index in range(18)])
        data["extensions"][0]["name"] = "</script><script>not executable</script>"
        with tempfile.TemporaryDirectory(prefix="case03-arc-offline-") as temporary:
            with patch.object(tool.Path, "cwd", return_value=Path(temporary)):
                result = tool._write_report(data)
            for key in ("report_path", "resources_csv_path", "signals_csv_path", "snapshot_path"):
                self.assertLessEqual(Path(result[key]).stat().st_size, 4_800_000)
            self.assertEqual(result["provenance"], "SIMULATED")
            self.assertLessEqual(len(json.dumps(result).encode("utf-8")), 3500)
            restored = tool._unpack_snapshot(json.loads(Path(result["snapshot_path"]).read_text(encoding="utf-8")))
            self.assertEqual(restored, data)
            rows = list(csv.DictReader(io.StringIO(Path(result["resources_csv_path"]).read_text(encoding="utf-8-sig"))))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["arc_agent_version"], "1.9.300.0")
            self.assertEqual(json.loads(rows[0]["arc_extensions"]), data["extensions"])
            self.assertEqual(json.loads(rows[0]["arc_administration"]), data["resources"][0]["arc_administration"])
            markup = Path(result["report_path"]).read_text(encoding="utf-8")
            blob = re.search(r'<script id="evidence-data" type="application/json">([\s\S]*?)</script>', markup)[1]
            self.assertEqual(tool._unpack_snapshot(json.loads(blob)), data)
            self.assertIn('id="arc-admin-filter"', markup)
            self.assertNotIn("</script><script>not executable</script>", markup)
            self.assertIn("logo company", markup)
            self.assertIn("connect-src 'none'", markup)

    def test_complete_collector_preserves_measurements_and_adds_only_one_fixed_source(self):
        client = existing.ReadOnlyCollectorTests().client()
        original = client.request

        def request(method, url, source, body=None, deadline=None):
            reply = original(method, url, source, body, deadline)
            if source == "inventory":
                reply["data"][0] = machine_row()
            elif source == "arc_extensions":
                return page([extension_row()])
            return reply

        client.request = request
        configured = config([baseline()])
        with patch.object(tool, "AzureReadClient", return_value=client):
            data = tool._collect_live(configured, parameters(), REFERENCE)
        self.assertTrue(client.closed)
        self.assertEqual(data["summary"]["resources"], 2)
        self.assertEqual(data["summary"]["metric_series"], 4)
        self.assertEqual(len([call for call in client.calls if call[2] == "arc_extensions"]), 1)
        arc = next(row for row in data["resources"] if row["resource_id"] == ARC_ID)
        self.assertEqual(arc["series_count"], 3)
        self.assertEqual(arc["heartbeat"]["last_sample_utc"], "2026-10-09T17:58:00Z")
        self.assertEqual(arc["arc_administration"]["agent_version_status"], "below_review_target")
        self.assertEqual(data["summary"]["arc_extensions_observed"], 1)
        self.assertEqual(next(row["status"] for row in data["sources"] if row["source"] == "Perf"), "not_collected")

    def test_unconfigured_optional_policy_preserves_legacy_metric_assessment_and_owner_counts(self):
        client = existing.ReadOnlyCollectorTests().client()
        with patch.object(tool, "AzureReadClient", return_value=client):
            data = tool._collect_live(config(), parameters(), REFERENCE)
        resource = next(row for row in data["resources"] if row["resource_id"] == ARC_ID)
        self.assertEqual(resource["assessment"], "observed")
        self.assertEqual(resource["series_count"], 3)
        self.assertEqual(resource["arc_administration"]["assessment"], "unknown")
        self.assertTrue(any(row["kind"] == "arc_administration_unknown" for row in data["signals"]))
        self.assertFalse(any(row["resource_id"] == ARC_ID for row in data["actions"]))
        queried = tool._query(data, parameters(view="resources", state="observed"))
        self.assertEqual(queried["total_matched"], 1)
        self.assertEqual(queried["rows"][0]["arc_administration"]["assessment"], "unknown")
        self.assertEqual(data["summary"]["arc_administration_unknown"], 1)

    def test_large_inventory_still_fails_before_local_filters_or_extension_reads(self):
        client = existing.ReadOnlyCollectorTests().client()
        original = client.request

        def request(method, url, source, body=None, deadline=None):
            if source == "inventory":
                return page([{**machine_row(), "id": ARC_ID + str(index)} for index in range(801)])
            return original(method, url, source, body, deadline)

        client.request = request
        with patch.object(tool, "AzureReadClient", return_value=client), self.assertRaises(tool.EvidenceError) as caught:
            tool._collect_live(config(), parameters(hosting="arc", resource_name="one-machine", resource_group="test-rg"), REFERENCE)
        self.assertEqual(caught.exception.code, "scope_too_large")
        self.assertEqual(caught.exception.source, "inventory")
        self.assertFalse(any(call[2] == "arc_extensions" for call in client.calls))
        self.assertEqual(tool.MAX_RESOURCES, 500)
        self.assertEqual(len(tool.RESOURCE_TYPES), 15)


class ArcCardinalityTests(unittest.TestCase):
    def test_actual_500_resource_boundary_is_independent_of_extension_rows(self):
        rows = [{**machine_row(), "id": ARC_ID + str(index), "name": "test-arc-" + str(index)} for index in range(500)]
        resources = tool._normalize_resources(rows, SUBSCRIPTION)
        self.assertEqual(len(resources), 500)
        with self.assertRaises(tool.EvidenceError) as caught:
            tool._normalize_resources(rows + [{**machine_row(), "id": ARC_ID + "extra"}], SUBSCRIPTION)
        self.assertEqual(caught.exception.code, "scope_too_large")

    def test_5000_extension_rows_use_five_pages_and_oversized_csv_fails_before_writing(self):
        started = time.monotonic()
        rows = [{**extension_row("extension-" + str(index)), "name": "SIMULATED-" + str(index) + "-" + "x" * 170}
                for index in range(5000)]
        replies = [page(rows[start:start + 1000], 5000, "page-" + str(start) if start < 4000 else None)
                   for start in range(0, 5000, 1000)]
        client = ExtensionClient(replies)
        resources = tool._normalize_resources([machine_row()], SUBSCRIPTION)
        extensions, receipt = tool._collect_arc_extensions(client, config(), resources, REFERENCE)
        self.assertEqual(len(client.calls), 5)
        self.assertEqual(receipt["status"], "complete")
        self.assertEqual(receipt["declared_subscription_rows"], 5000)
        self.assertEqual(len(extensions), 5000)
        self.assertEqual(len({row["extension_id"] for row in extensions}), 5000)
        data = tool._finish_snapshot(resources, [], [receipt], [], {}, [], [], config(),
                                     parameters(), REFERENCE, 1, extensions)
        data["provenance"] = "SIMULATED"
        self.assertEqual(data["summary"]["resources"], 1)
        self.assertEqual(data["summary"]["arc_extensions_observed"], 5000)
        self.assertEqual(tool._unpack_snapshot(tool._pack_snapshot(data)), data)
        csv_text = tool._csv_document(tool._csv_context(data, tool._resource_export_rows(data)),
                                      tool.CSV_CONTEXT_FIELDS + tool.RESOURCE_CSV_FIELDS)
        self.assertGreater(len(csv_text.encode("utf-8-sig")), 4_800_000)
        with tempfile.TemporaryDirectory(prefix="case03-arc-cap-") as temporary:
            with patch.object(tool.Path, "cwd", return_value=Path(temporary)), self.assertRaises(tool.EvidenceError) as caught:
                tool._write_report(data)
            self.assertEqual(caught.exception.code, "artifact_size_exceeded")
            self.assertFalse((Path(temporary) / "infrastructure-operations-reports").exists())
        self.assertEqual(len(data["extensions"]), 5000)
        self.assertLess(time.monotonic() - started, 30)

    def test_monthly_100_resources_400_extensions_and_43200_points_keep_four_complete_files(self):
        started = time.monotonic()
        params = parameters(operation="report", period="previous_month")
        start = tool._time(params["window"]["start_utc"], "test")
        raw_inventory = [{**machine_row(), "id": ARC_ID + "-" + str(index), "name": "test-arc-" + str(index)}
                         for index in range(100)]
        resources = tool._normalize_resources(raw_inventory, SUBSCRIPTION)
        raw_extensions = [{**extension_row("extension-" + str(index)), "id": resource["resource_id"] + "/extensions/extension-" + str(index)}
                          for resource in resources for index in range(4)]
        extensions = tool._normalize_arc_extensions(raw_extensions, resources, SUBSCRIPTION, REFERENCE)
        log_rows = []
        for resource in resources[:20]:
            for index in range(720):
                instant = start + timedelta(hours=index)
                timestamp = tool._iso(instant)
                common = {"resource_id": resource["resource_id"], "time_utc": timestamp,
                          "first_sample_utc": timestamp, "last_sample_utc": tool._iso(instant + timedelta(seconds=4))}
                log_rows.append(existing.log_bin(2, **common))
                log_rows.append(existing.log_bin(2048, namespace="Memory", name="AvailableMB",
                                                tags='{"vm.azm.ms/memorySizeMB":"4096"}', **common))
        self.assertEqual(len(log_rows), 28800)
        self.assertLess(len(log_rows), tool.MAX_SOURCE_ROWS)
        series, _ = tool._normalize_guest(log_rows, "InsightsMetrics", WORKSPACE, resources, params["window"])
        sources = [tool._source("inventory", "complete", REFERENCE, 100),
                   tool._source("arc_extensions", "complete", REFERENCE, 400, pages=1,
                                subscription_rows_read=400, declared_subscription_rows=400),
                   tool._source("InsightsMetrics", "complete", REFERENCE, 28800)]
        data = tool._finish_snapshot(resources, series, sources, [], {}, [], [], config([baseline()]),
                                     params, REFERENCE, 100, extensions)
        data["provenance"] = "SIMULATED"
        self.assertEqual(data["summary"]["resources"], 100)
        self.assertEqual(data["summary"]["metric_series"], 60)
        self.assertEqual(data["summary"]["resources_with_metrics"], 20)
        self.assertEqual(sum(len(row["points"]) for row in series), 43200)
        self.assertEqual(data["window"]["start_utc"], "2026-09-01T00:00:00Z")
        self.assertEqual(data["window"]["end_utc"], "2026-10-01T00:00:00Z")
        with tempfile.TemporaryDirectory(prefix="case03-arc-month-") as temporary:
            with patch.object(tool.Path, "cwd", return_value=Path(temporary)):
                result = tool._write_report(data)
            self.assertLessEqual(len(json.dumps(result).encode("utf-8")), 3500)
            self.assertEqual(result["provenance"], "SIMULATED")
            for key in ("report_path", "resources_csv_path", "signals_csv_path", "snapshot_path"):
                self.assertLessEqual(Path(result[key]).stat().st_size, 4_800_000)
            restored = tool._unpack_snapshot(json.loads(Path(result["snapshot_path"]).read_text(encoding="utf-8")))
            self.assertEqual(restored, data)
            exported = list(csv.DictReader(io.StringIO(Path(result["resources_csv_path"]).read_text(encoding="utf-8-sig"))))
            self.assertEqual(len(exported), 100)
            self.assertEqual(sum(len(json.loads(row["arc_extensions"])) for row in exported), 400)
        self.assertLess(time.monotonic() - started, 30)


@unittest.skipUnless(importlib.util.find_spec("playwright"), "Optional installed Playwright enables the offline browser check.")
class ArcBrowserTests(unittest.TestCase):
    def test_offline_filters_details_downloads_and_mobile_layout_keep_complete_evidence(self):
        from playwright.sync_api import Error, sync_playwright

        data = simulated_snapshot([baseline()], rows=[extension_row("extension-" + str(index)) for index in range(18)])
        data["provenance"] = "SIMULATED"
        data["extensions"][0]["name"] = '<img src=x onerror="window.untrustedExecuted=true">'
        resources = data["resources"] + inventory(VM_ID, "microsoft.compute/virtualmachines", "test-vm")
        data = tool._finish_snapshot(resources, [], data["sources"], [], {}, [], [], config([baseline()]),
                                     parameters(), REFERENCE, 2, data["extensions"])
        data["provenance"] = "SIMULATED"
        markup = tool._render_html(data, tool._json_document(data))
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
            except Error as exc:
                if "is not found" in str(exc) or "Executable doesn't exist" in str(exc):
                    self.skipTest("Optional local Microsoft Edge installation is not available.")
                raise
            try:
                context = browser.new_context(accept_downloads=True, viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                errors, requests = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: requests.append(request.url))
                page.set_content(markup, wait_until="load")
                self.assertEqual(page.evaluate("window.infraReport.snapshot"), data)
                self.assertIsNone(page.evaluate("window.untrustedExecuted"))
                self.assertEqual(page.locator(".company-logo").inner_text(), "logo company")
                page.select_option("#arc-admin-filter", "below_target")
                self.assertEqual(page.evaluate("window.infraReport.getFilteredResources().length"), 1)
                inspector = page.locator("#inspector").inner_text()
                self.assertIn("Arc administration and extensions (18)", inspector)
                self.assertIn("1.9.300.0", inspector)
                self.assertIn("1.9.1", inspector)
                self.assertIn("Unknown / not evaluated", inspector)
                self.assertIn(baseline()["reference"], inspector)
                self.assertIn("Neither Succeeded nor an extension name proves sensor health", inspector)
                with page.expect_download() as downloaded:
                    page.click("#export-resources")
                rows = list(csv.DictReader(io.StringIO(Path(downloaded.value.path()).read_text(encoding="utf-8-sig"))))
                self.assertEqual(len(rows), 1)
                self.assertEqual(json.loads(rows[0]["arc_extensions"]), data["extensions"])
                with page.expect_download() as downloaded:
                    page.click("[data-export-resource]")
                focused = json.loads(Path(downloaded.value.path()).read_text(encoding="utf-8"))
                self.assertEqual(focused["extensions"], data["extensions"])
                self.assertEqual(focused["arc_baselines"], data["arc_baselines"])
                with page.expect_download() as downloaded:
                    page.click("#export-json")
                self.assertEqual(json.loads(Path(downloaded.value.path()).read_text(encoding="utf-8")), data)
                page.click("#reset")
                self.assertEqual(page.evaluate("window.infraReport.getFilteredResources().length"), 2)
                page.fill("#search", "Synthetic.Publisher")
                self.assertEqual(page.evaluate("window.infraReport.getFilteredResources().length"), 1)
                for width in (1440, 390):
                    page.set_viewport_size({"width": width, "height": 900})
                    page.wait_for_timeout(200)
                    self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                self.assertEqual(requests, [], "Offline report must not make network or external image requests.")
                self.assertEqual(errors, [])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
