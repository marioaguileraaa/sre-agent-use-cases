"""Optional, local-only replays of ignored real API fixtures.

These tests make no network calls. Same-type definition IDs are rebound only
to exercise response schemas; a replay is not a LIVE collection or a proof of
current metric availability. No fixture values/identifiers are committed.
"""

import copy
import hashlib
import importlib.util
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

SCENARIO = Path(__file__).resolve().parents[1]
FIXTURES = SCENARIO / "handoff-inputs"
SPEC = importlib.util.spec_from_file_location("actual_shape_tool", SCENARIO / "generate-infrastructure-operations-report.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def load(path):
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    return result["body"]


def source_resource(resource_id, resource_type):
    return {
        "resource_id": resource_id.casefold(), "resource_type": resource_type.casefold(),
        "name": resource_id.rsplit("/", 1)[-1],
    }


@unittest.skipUnless(FIXTURES.is_dir(), "Actual API handoff is private, optional and ignored.")
class ActualSourceShapeTests(unittest.TestCase):
    def test_exact_failed_full_month_now_fits_four_plain_artifacts_losslessly(self):
        path = FIXTURES / "actual-full-previous-month-normalized.json"
        summary_path = FIXTURES / "actual-full-month-fixture-summary.json"
        if not path.is_file() or not summary_path.is_file():
            self.skipTest("Exact failed monthly source fixture has not arrived.")
        raw = path.read_bytes()
        summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), summary["sha256"])
        data = json.loads(raw)
        self.assertEqual(len(data["resources"]), summary["resources"])
        self.assertEqual(len(data["series"]), summary["series"])
        self.assertEqual(sum(len(row["points"]) for row in data["series"]), summary["points"])
        self.assertEqual(data["window"], summary["window"])
        self.assertGreater(summary["original_complete_artifact_sizes"]["HTML"], tool.MAX_ARTIFACT_BYTES)
        self.assertGreater(summary["original_complete_artifact_sizes"]["JSON"], tool.MAX_ARTIFACT_BYTES)
        with tempfile.TemporaryDirectory(prefix="case03-monthly-test-") as temporary:
            with patch.object(tool.Path, "cwd", return_value=Path(temporary)):
                response = tool._write_report(data)
            for key in ("report_path", "resources_csv_path", "signals_csv_path", "snapshot_path"):
                self.assertLessEqual(Path(response[key]).stat().st_size, tool.MAX_ARTIFACT_BYTES, key)
            encoded = json.loads(Path(response["snapshot_path"]).read_text(encoding="utf-8"))
            self.assertEqual(encoded["encoding_version"], "2.0")
            self.assertEqual(tool._unpack_snapshot(encoded), data)
            self.assertLessEqual(len(json.dumps(response).encode("utf-8")), tool.TRANSPORT_BUDGET_BYTES)

    def test_actual_month_package_images_do_not_create_writable_capacity_warnings_or_drop_points(self):
        path = FIXTURES / "actual-full-previous-month-normalized.json"
        if not path.is_file():
            self.skipTest("Exact full-month source fixture has not arrived.")
        data = json.loads(path.read_bytes())
        before = json.dumps(data["series"], sort_keys=True, separators=(",", ":"))
        image_ids = {
            row["series_id"] for row in data["series"]
            if row["metric"] == "disk_free_percent"
            and isinstance(row["dimensions"].get("vm.azm.ms/mountId"), str)
            and tool.re.fullmatch(tool.POLICY["package_image_mount_pattern"], row["dimensions"]["vm.azm.ms/mountId"])
        }
        self.assertTrue(image_ids)
        signals = tool._metric_signals(data["series"])
        self.assertEqual(json.dumps(data["series"], sort_keys=True, separators=(",", ":")), before)
        self.assertEqual(len(data["series"]), 269)
        self.assertEqual(sum(len(row["points"]) for row in data["series"]), 171059)
        self.assertFalse(any(row["series_id"] in image_ids and row["kind"] == "sustained_pressure" for row in signals))
        observed_ids = {row["series_id"] for row in signals if row["kind"] == "package_image_capacity"}
        self.assertTrue(observed_ids)
        self.assertTrue(observed_ids.issubset(image_ids))

    def fixed_resources(self):
        path = FIXTURES / "fixed-inventory-actual.json"
        if not path.is_file():
            self.skipTest("Final fixed inventory was not supplied in this private handoff.")
        wrapper = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertEqual(wrapper["query"], tool._inventory_query())
        payload = wrapper["body"]
        subscription = payload["data"][0]["id"].split("/")[2]
        resources = tool._normalize_resources(payload["data"], subscription)
        self.assertEqual(len(resources), payload["totalRecords"])
        self.assertEqual(len(resources), len({row["resource_id"] for row in resources}))
        return resources, subscription

    def test_exact_fixed_guest_queries_normalize_real_24h_and_30d_shapes(self):
        resources, _ = self.fixed_resources()
        compute = [row for row in resources if row["resource_type"] in tool.COMPUTE_TYPES]
        ids = [row["resource_id"] for row in compute]
        for suffix in ("24h", "30d"):
            for table in ("Heartbeat", "Perf", "InsightsMetrics"):
                path = FIXTURES / ("fixed-" + table.casefold() + "-" + suffix + "-actual.json")
                if not path.is_file():
                    self.skipTest("Final fixed aggregate was not supplied: " + path.name)
                wrapper = json.loads(path.read_text(encoding="utf-8-sig"))
                window = wrapper["window"]
                self.assertEqual(wrapper["query"], tool._log_query(table, ids, window))
                rows = tool._log_rows(wrapper["body"], table)
                with self.subTest(table=table, window=suffix):
                    if table == "Heartbeat":
                        heartbeat = tool._normalize_heartbeat(rows, wrapper["workspace_id"], compute, window)
                        self.assertEqual(len(heartbeat), len({row["resource_id"] for row in heartbeat}))
                        self.assertTrue(all(row["resource_id"] in ids for row in heartbeat))
                    else:
                        series, notes = tool._normalize_guest(rows, table, wrapper["workspace_id"], compute, window)
                        self.assertTrue(all(row["resource_id"] in ids for row in series))
                        self.assertFalse(notes)
                        if table == "Perf":
                            self.assertEqual(series, [], "A valid empty Perf table must not create zero-filled measurements.")
                        else:
                            self.assertTrue(series)
                            self.assertTrue(all(row["summary"]["observed_bins"] > 0 for row in series))
                            self.assertEqual(sum(len(row["points"]) for row in series),
                                             len(rows) + sum(row["name"] == "AvailableMB" for row in rows),
                                             "Derived memory percentage preserves rather than replaces byte evidence.")

    def test_complete_health_handoff_replays_validated_pages_and_exact_ids(self):
        resources, subscription = self.fixed_resources()
        path = FIXTURES / "resource-health-complete-actual.json"
        if not path.is_file():
            self.skipTest("Full Resource Health continuation has not arrived.")
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        pages = document["pages"]
        initial = tool.ARM_ORIGIN + "/subscriptions/" + subscription + "/providers/Microsoft.ResourceHealth/availabilityStatuses?api-version=" + tool.HEALTH_VERSION

        class Client:
            def __init__(self):
                self.index = 0

            def request(self, method, url, source):
                expected = initial if self.index == 0 else pages[self.index - 1]["nextLink"]
                if method != "GET" or url != expected or source != "resource_health":
                    raise AssertionError("Continuation replay changed request identity.")
                result = pages[self.index]
                self.index += 1
                return result

        rows, count = tool._arm_list(Client(), initial, "resource_health")
        self.assertEqual(count, len(pages))
        self.assertEqual(len(rows), sum(len(page["value"]) for page in pages))
        wrapper = json.loads((FIXTURES / "fixed-insightsmetrics-24h-actual.json").read_text(encoding="utf-8-sig"))
        health, _ = tool._normalize_health(rows, resources, wrapper["window"], tool._time(wrapper["window"]["end_utc"], "test"))
        self.assertTrue(health)
        self.assertTrue(set(health).issubset({row["resource_id"] for row in resources}))

    def test_actual_30d_guest_evidence_is_lossless_and_below_plain_artifact_limit(self):
        resources, subscription = self.fixed_resources()
        path = FIXTURES / "fixed-insightsmetrics-30d-actual.json"
        if not path.is_file():
            self.skipTest("Final 30-day aggregate has not arrived.")
        wrapper = json.loads(path.read_text(encoding="utf-8-sig"))
        compute = [row for row in resources if row["resource_type"] in tool.COMPUTE_TYPES]
        window = wrapper["window"]
        reference = tool._time(window["end_utc"], "test")
        params = tool._parameters("report", "summary", "all", "", "", "", "", "all", "all", "all",
                                  "custom", window["start_utc"], window["end_utc"], "PT1H", 20, 0, reference)
        rows = tool._log_rows(wrapper["body"], "InsightsMetrics")
        series, _ = tool._normalize_guest(rows, "InsightsMetrics", wrapper["workspace_id"], compute, params["window"])
        config = {"subscription_id": subscription, "tenant_id": "00000000-0000-4000-8000-000000000000",
                  "workspace_ids": [wrapper["workspace_id"]]}
        data = tool._finish_snapshot(resources, series, [], [], {}, [], [], config, params, reference, len(resources))
        data["provenance"] = "ACTUAL SOURCE REPLAY"
        encoded = tool._json_document(data)
        self.assertEqual(tool._unpack_snapshot(json.loads(encoded)), data)
        self.assertLessEqual(len(encoded.encode("utf-8")), tool.MAX_ARTIFACT_BYTES)
        self.assertLessEqual(len(tool._render_html(data, encoded).encode("utf-8")), tool.MAX_ARTIFACT_BYTES)
        for view in tool.VIEWS:
            offset, returned, expected = 0, 0, None
            while True:
                query = dict(params, operation="query", view=view, offset=offset)
                response = tool._query(data, query)
                with self.subTest(view=view, offset=offset):
                    self.assertLessEqual(len(json.dumps(response, allow_nan=False).encode("utf-8")),
                                         tool.TRANSPORT_BUDGET_BYTES)
                    self.assertEqual(response["returned"], len(response["rows"]))
                    if expected is not None:
                        self.assertEqual(response["total_matched"], expected)
                expected = response["total_matched"]
                returned += response["returned"]
                if not response["has_more"]:
                    self.assertIsNone(response["next_offset"])
                    break
                self.assertGreater(response["next_offset"], offset)
                offset = response["next_offset"]
            self.assertEqual(returned, expected, view)

    def test_every_provided_definition_family_has_a_valid_native_contract(self):
        files = list(FIXTURES.glob("metric-definitions-*-actual.json"))
        self.assertTrue(files, "Expected the private definition handoff.")
        for path in files:
            wrapper = json.loads(path.read_text(encoding="utf-8-sig"))
            payload = wrapper["body"]
            if wrapper["http_status"] != 200:
                with self.subTest(unsupported=path.name):
                    self.assertEqual(wrapper["resource"]["type"], "microsoft.hybridcompute/machines")
                    self.assertNotIn("microsoft.hybridcompute/machines", tool.PLATFORM_METRICS)
                    self.assertTrue(payload.get("code"))
                continue
            first = payload["value"][0]
            resource_id = first["resourceId"]
            parts = resource_id.split("/")
            resource_type = parts[6] + "/" + parts[7]
            if resource_type.casefold() not in tool.PLATFORM_METRICS:
                continue
            window = {
                "start_utc": "2026-09-01T00:00:00Z", "end_utc": "2026-10-01T00:00:00Z",
                "grain_seconds": 3600,
            }
            with self.subTest(family=path.name):
                specs, absent = tool._metric_specs(payload, source_resource(resource_id, resource_type), window, "all")
                self.assertTrue(specs or absent)
                for spec in specs:
                    self.assertGreaterEqual(spec["grain_seconds"], 3600)
                    self.assertTrue(spec["unit"])
                    self.assertFalse(spec["dimension_names"], "Actual optional dimensions must not explode the report scope.")

    def test_native_samples_preserve_real_phase_and_missing_values(self):
        files = list(FIXTURES.glob("metrics-*-actual.json"))
        self.assertTrue(files, "Expected the private native metric handoff.")
        for path in files:
            payload = load(path)
            first = payload["value"][0]
            resource_id = first["id"].casefold().split("/providers/microsoft.insights/metrics/", 1)[0]
            parts = resource_id.split("/")
            resource_type = parts[6] + "/" + parts[7]
            definition_path = FIXTURES / ("metric-definitions-" + resource_type.replace("/", "-") + "-actual.json")
            definitions = copy.deepcopy(load(definition_path))
            for definition in definitions["value"]:
                definition["resourceId"] = resource_id
            start, end = payload["timespan"].split("/")
            window = {"start_utc": start, "end_utc": end, "grain_seconds": tool._duration_seconds(payload["interval"], "test")}
            specs, _ = tool._metric_specs(definitions, source_resource(resource_id, resource_type), window, "all")
            available = {spec["native_name"].casefold(): spec for spec in specs}
            selected_records = [row for row in payload["value"] if row["name"]["value"].casefold() in available]
            selected_specs = [available[row["name"]["value"].casefold()] for row in selected_records]
            current = dict(payload, value=selected_records)
            with self.subTest(sample=path.name):
                series = tool._normalize_platform(current, source_resource(resource_id, resource_type), selected_specs, window)
                self.assertTrue(series)
                for item in series:
                    self.assertTrue(item["points"])
                    self.assertEqual(item["bin_phase_seconds"], int(tool._time(item["points"][0]["time_utc"], "test").timestamp()) % item["grain_seconds"])
                timestamp_only = all(
                    set(point) == {"timeStamp"}
                    for record in selected_records for trace in record["timeseries"] for point in trace["data"]
                )
                if timestamp_only:
                    self.assertTrue(all(item["summary"]["observed_bins"] == 0 for item in series))
                    self.assertTrue(all(item["summary"]["mean"] is None for item in series))

    def test_health_first_page_is_not_a_complete_subscription_count(self):
        payload = load(FIXTURES / "resource-health-actual.json")
        self.assertTrue(payload.get("nextLink"), "This fixture deliberately includes a continuation.")
        self.assertIn("availabilitystatuses", payload["nextLink"].casefold())
        self.assertEqual(tool.HEALTH_VERSION, "2022-10-01")


if __name__ == "__main__":
    unittest.main()
