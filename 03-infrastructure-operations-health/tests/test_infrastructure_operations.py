"""Offline contract tests. All fixtures in this module are explicitly synthetic."""

import importlib.util
import ast
import io
import inspect
import json
import shutil
import struct
import os
import tempfile
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from unittest.mock import patch

TOOL_PATH = Path(__file__).resolve().parents[1] / "generate-infrastructure-operations-report.py"
SPEC = importlib.util.spec_from_file_location("infrastructure_operations", TOOL_PATH)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)

SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"
CLIENT = "33333333-3333-4333-8333-333333333333"
WORKSPACE = "44444444-4444-4444-8444-444444444444"
ARC_ID = f"/subscriptions/{SUBSCRIPTION}/resourcegroups/test-rg/providers/microsoft.hybridcompute/machines/test-arc"
VM_ID = f"/subscriptions/{SUBSCRIPTION}/resourcegroups/test-rg/providers/microsoft.compute/virtualmachines/test-vm"
REFERENCE = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)


def parameters(**overrides):
    values = {
        "operation": "query", "view": "summary", "hosting": "all",
        "resource_group": "", "resource_name": "", "resource_id": "", "resource_type": "",
        "metric": "all", "state": "all", "severity": "all", "period": "last_2h",
        "start_utc": "", "end_utc": "", "grain": "auto", "limit": 20, "offset": 0,
        "reference": REFERENCE,
    }
    values.update(overrides)
    return tool._parameters(**values)


def inventory(resource_id=ARC_ID, kind="microsoft.hybridcompute/machines", name="test-arc"):
    return tool._normalize_resources([{
        "id": resource_id, "name": name, "type": kind, "resourceGroup": "test-rg",
        "location": "test-region", "tags": {"Owner": "Synthetic test team"},
        "properties": {"status": "Connected", "osType": "Linux"},
    }], SUBSCRIPTION)


def log_bin(value=30, count=5, timestamp="2026-10-09T16:00:00Z", **overrides):
    result = {
        "resource_id": ARC_ID, "namespace": "Processor", "name": "UtilizationPercentage",
        "tags": '{"vm.azm.ms/totalCpus":"2"}', "time_utc": timestamp,
        "mean": value, "minimum": value, "maximum": value, "total": value * count,
        "count": count, "first_sample_utc": timestamp,
        "last_sample_utc": timestamp.replace(":00Z", ":04Z"),
    }
    result.update(overrides)
    return result


def definition(name="Percentage CPU", unit="Percent", aggregations=None, dimensions=None):
    return {
        "resourceId": VM_ID,
        "name": {"value": name}, "namespace": "Microsoft.Compute/virtualMachines",
        "unit": unit, "primaryAggregationType": "Average",
        "supportedAggregationTypes": aggregations if aggregations is not None else ["Average", "Minimum", "Maximum"],
        "metricAvailabilities": [{"timeGrain": "PT5M", "retention": "P93D"}, {"timeGrain": "PT1H", "retention": "P93D"}],
        "dimensions": dimensions or [],
    }


def snapshot(resource_count=2, metric_filter="all"):
    resources = inventory()
    for index in range(1, resource_count):
        resource_id = VM_ID + str(index)
        resources.extend(inventory(resource_id, "microsoft.compute/virtualmachines", "test-vm" + str(index)))
    series, _ = tool._normalize_guest([log_bin()], "InsightsMetrics", WORKSPACE, resources, parameters()["window"])
    sources = [tool._source("inventory", "complete", REFERENCE, resource_count),
               tool._source("InsightsMetrics", "complete", REFERENCE, 1)]
    config = {"subscription_id": SUBSCRIPTION, "tenant_id": TENANT, "workspace_ids": [WORKSPACE]}
    return tool._finish_snapshot(resources, series, sources, [], {}, [], [], config,
                                 parameters(metric=metric_filter), REFERENCE, resource_count)


class ParameterTests(unittest.TestCase):
    def test_main_signature_and_schema_remain_identical(self):
        schema = json.loads((TOOL_PATH.parent / "tool-parameters.schema.json").read_text(encoding="utf-8"))
        signature = inspect.signature(tool.main)
        self.assertEqual(set(signature.parameters), set(schema["properties"]))
        for key, parameter in signature.parameters.items():
            self.assertEqual(parameter.default, schema["properties"][key]["default"], key)
        self.assertEqual(set(schema["properties"]["metric"]["enum"]), {"all", *tool.METRIC_INFO})

    def test_unconfigured_main_is_complete_small_error_without_network(self):
        with patch.object(tool, "AzureReadClient") as client:
            result = tool.main()
        client.assert_not_called()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "configuration_required")
        self.assertFalse(result["artifacts_created"])
        self.assertLessEqual(tool._response_bytes(result), 3500)

    def test_monthly_default_is_previous_utc_calendar_month(self):
        result = parameters(operation="report", period="auto")
        self.assertEqual(result["window"]["start_utc"], "2026-09-01T00:00:00Z")
        self.assertEqual(result["window"]["end_utc"], "2026-10-01T00:00:00Z")
        self.assertEqual(result["window"]["grain"], "PT1H")
        self.assertEqual(result["window"]["expected_bins"], 720)

    def test_live_default_is_last_24_hours(self):
        result = parameters(period="auto")
        self.assertEqual(result["window"]["period"], "last_24h")
        self.assertEqual(result["window"]["grain"], "PT5M")

    def test_dense_month_is_rejected_not_truncated(self):
        with self.assertRaises(tool.EvidenceError) as caught:
            parameters(period="previous_month", grain="PT5M")
        self.assertEqual(caught.exception.code, "window_too_dense")

    def test_explicit_offset_is_normalized_to_utc(self):
        result = parameters(period="custom", start_utc="2026-10-09T10:00:00-04:00",
                            end_utc="2026-10-09T11:00:00-04:00")
        self.assertEqual(result["window"]["start_utc"], "2026-10-09T14:00:00Z")

    def test_unsupported_filters_are_explicit(self):
        for overrides in (
            {"view": "resources", "severity": "warning"},
            {"view": "coverage", "state": "unknown"},
            {"operation": "report", "view": "metrics"},
            {"period": "last_2h", "start_utc": "2026-10-09T10:00:00Z"},
            {"resource_type": "Microsoft.KeyVault/vaults/secrets"},
            {"resource_name": "x\n| union secrets"},
            {"limit": True},
            {"period": "custom", "start_utc": "2026-10-09T10:00:00", "end_utc": "2026-10-09T11:00:00"},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(tool.EvidenceError):
                parameters(**overrides)

    def test_default_json_serializer_is_the_actual_budget(self):
        response = {"note": "\u00e1" * 600}
        self.assertGreater(tool._response_bytes(response), 3500)
        self.assertLess(len(json.dumps(response, ensure_ascii=False).encode()), 3500)
        with self.assertRaises(tool.EvidenceError):
            tool._budget(response)


class ScopeTests(unittest.TestCase):
    def test_real_owner_tag_aliases_are_supported_without_guessing(self):
        self.assertEqual(tool._owner({"Responsable": "Synthetic owner"}), "Synthetic owner")
        self.assertIsNone(tool._owner({"Environment": "Production"}))

    def test_valid_internal_spaces_in_database_ids_are_encoded_not_rejected(self):
        value = f"/subscriptions/{SUBSCRIPTION}/resourcegroups/test-rg/providers/microsoft.sql/servers/test/databases/Database One"
        self.assertEqual(tool._resource_id(value, SUBSCRIPTION, "test"), value.casefold())

    def test_arc_connection_is_not_guest_health(self):
        row = inventory()[0]
        self.assertEqual(row["arc_connection"], "Connected")
        self.assertIsNone(row["health"])
        self.assertEqual(row["assessment"], "unknown")

    def test_resource_id_cannot_escape_subscription(self):
        for value in (ARC_ID.replace(SUBSCRIPTION, TENANT), ARC_ID + "?x=1", ARC_ID + "/../secret", "https://example.com"):
            with self.subTest(value=value), self.assertRaises(tool.EvidenceError):
                tool._resource_id(value, SUBSCRIPTION, "test")

    def test_local_resource_filters(self):
        row = inventory()[0]
        self.assertTrue(tool._resource_matches(row, parameters(hosting="arc", resource_name="ARC", resource_group="TEST-RG")))
        self.assertFalse(tool._resource_matches(row, parameters(hosting="azure")))

    def test_source_endpoints_are_read_only_and_allowlisted(self):
        config = {"subscription_id": SUBSCRIPTION, "workspace_ids": [WORKSPACE]}
        good = tool.ARM_ORIGIN + VM_ID + "/providers/Microsoft.Insights/metrics?api-version=2023-10-01"
        self.assertEqual(tool._validate_endpoint("GET", good, None, config), tool.ARM_ORIGIN + "/.default")
        for method, url in (
            ("POST", good),
            ("GET", tool.ARM_ORIGIN + VM_ID + "/listKeys"),
            ("GET", good.replace("management.azure.com", "example.com")),
            ("GET", good.replace(SUBSCRIPTION, TENANT)),
            ("GET", good.replace("management.azure.com", "management.azure.com:bad")),
            ("POST", tool.LOGS_ORIGIN + "/v1/workspaces/" + TENANT + "/query"),
        ):
            with self.subTest(url=url), self.assertRaises(tool.EvidenceError):
                tool._validate_endpoint(method, url, None, config)

    def test_pagination_preserves_scope_and_rejects_repeated_query_keys(self):
        initial = tool.ARM_ORIGIN + f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.AlertsManagement/alerts?api-version=2019-03-01&timeRange=30d"
        valid = initial + "&$skipToken=opaque"
        self.assertEqual(tool._next_link(valid, initial, "test"), valid)
        for invalid in (
            valid.replace("30d", "7d"),
            valid.replace("&timeRange=30d", ""),
            valid + "&api-version=2019-03-01",
            valid.replace("management.azure.com", "example.com"),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(tool.EvidenceError):
                tool._next_link(invalid, initial, "test")


class GuestTelemetryTests(unittest.TestCase):
    def test_vm_insights_numeric_and_string_memory_capacity(self):
        for capacity in (4096, "4096"):
            row = log_bin(1024, namespace="Memory", name="AvailableMB",
                          tags=json.dumps({"vm.azm.ms/memorySizeMB": capacity}))
            series, notes = tool._normalize_guest([row], "InsightsMetrics", WORKSPACE, inventory(), parameters()["window"])
            self.assertFalse(notes)
            by_metric = {item["metric"]: item for item in series}
            self.assertEqual(by_metric["memory_available_bytes"]["summary"]["mean"], 1024 * 1048576)
            self.assertEqual(by_metric["memory_available_percent"]["summary"]["mean"], 25)

    def test_memory_capacity_absent_is_not_an_invented_percentage(self):
        row = log_bin(1024, namespace="Memory", name="AvailableMB", tags="{}")
        series, notes = tool._normalize_guest([row], "InsightsMetrics", WORKSPACE, inventory(), parameters()["window"])
        self.assertEqual([item["metric"] for item in series], ["memory_available_bytes"])
        self.assertEqual(notes[0]["code"], "memory_capacity_not_supplied")

    def test_cpu_weighting_counts_actual_log_records(self):
        rows = [log_bin(10, 1), log_bin(40, 3, timestamp="2026-10-09T16:05:00Z")]
        series, _ = tool._normalize_guest(rows, "InsightsMetrics", WORKSPACE, inventory(), parameters()["window"])
        self.assertEqual(series[0]["summary"]["mean"], 32.5)
        self.assertEqual(series[0]["summary"]["sample_count"], 4)
        self.assertEqual(series[0]["summary"]["missing_bins"], 22)

    def test_zero_is_observed_but_null_is_missing(self):
        row = log_bin(0)
        series, _ = tool._normalize_guest([row], "InsightsMetrics", WORKSPACE, inventory(), parameters()["window"])
        self.assertEqual(series[0]["summary"]["mean"], 0)
        self.assertEqual(series[0]["summary"]["observed_bins"], 1)

    def test_empty_perf_is_valid_and_does_not_create_zero_metrics(self):
        series, notes = tool._normalize_guest([], "Perf", WORKSPACE, inventory(), parameters()["window"])
        self.assertEqual(series, [])
        self.assertEqual(notes, [])

    def test_committed_memory_is_not_physical_usage(self):
        row = log_bin(95, object="Memory", name="% Committed Bytes In Use", instance="")
        series, _ = tool._normalize_guest([row], "Perf", WORKSPACE, inventory(), parameters()["window"])
        self.assertEqual(series[0]["metric"], "memory_commit_percent")
        self.assertIn("not physical RAM", series[0]["semantics"])

    def test_bad_guest_values_never_become_zero(self):
        for overrides in ({"mean": float("nan")}, {"count": 0}, {"tags": "not-json"}, {"resource_id": VM_ID}):
            with self.subTest(overrides=overrides), self.assertRaises(tool.EvidenceError):
                tool._normalize_guest([log_bin(**overrides)], "InsightsMetrics", WORKSPACE, inventory(), parameters()["window"])

    def test_partial_log_api_is_an_explicit_error(self):
        with self.assertRaises(tool.EvidenceError) as caught:
            tool._log_rows({"tables": [], "error": {"code": "PartialError"}}, "InsightsMetrics")
        self.assertEqual(caught.exception.code, "partial_log_query")

    def test_heartbeat_reports_recency_not_application_health(self):
        row = {"resource_id": ARC_ID, "count": 100, "first_sample_utc": "2026-10-09T16:01:00Z",
               "last_sample_utc": "2026-10-09T17:58:00Z"}
        result = tool._normalize_heartbeat([row], WORKSPACE, inventory(), parameters()["window"])[0]
        self.assertEqual(result["age_at_window_end_minutes"], 2)
        self.assertIn("not application health", result["qualification"])


class NativeMetricTests(unittest.TestCase):
    def test_native_bin_phase_is_preserved(self):
        resource = inventory(VM_ID, "microsoft.compute/virtualmachines", "test-vm")[0]
        specs, _ = tool._metric_specs({"value": [definition()]}, resource, parameters()["window"], "cpu_percent")
        payload = {"interval": "PT5M", "value": [{
            "id": VM_ID + "/providers/Microsoft.Insights/metrics/Percentage CPU",
            "name": {"value": "Percentage CPU"}, "unit": "Percent",
            "timeseries": [{"data": [{"timeStamp": "2026-10-09T16:04:00Z", "average": 50}]}],
        }]}
        result = tool._normalize_platform(payload, resource, specs, parameters()["window"])[0]
        self.assertEqual(result["bin_phase_seconds"], 240)
        self.assertEqual(result["points"][0]["time_utc"], "2026-10-09T16:04:00Z")

    def test_definition_and_metric_scope_mismatches_are_errors(self):
        resource = inventory(VM_ID, "microsoft.compute/virtualmachines", "test-vm")[0]
        wrong = definition()
        wrong["resourceId"] = ARC_ID
        with self.assertRaises(tool.EvidenceError):
            tool._metric_specs({"value": [wrong]}, resource, parameters()["window"], "cpu_percent")
        specs, _ = tool._metric_specs({"value": [definition()]}, resource, parameters()["window"], "cpu_percent")
        with self.assertRaises(tool.EvidenceError):
            tool._normalize_platform({"interval": "PT5M", "value": [{
                "id": ARC_ID + "/providers/Microsoft.Insights/metrics/Percentage CPU",
                "name": {"value": "Percentage CPU"}, "unit": "Percent", "timeseries": [],
            }]}, resource, specs, parameters()["window"])

    def test_count_metric_zero_is_real_but_count_statistic_does_not_invent_cpu(self):
        point = {"time_utc": "2026-10-09T16:00:00Z", "mean": None, "minimum": None,
                 "maximum": None, "total": None, "count": 0}
        counts = tool._series(VM_ID, "service_requests", "platform_metrics", "ServiceApiHit", "Count",
                              {}, parameters()["window"], [dict(point)], "API hits", "native_metric_Count", count_is_value=True)
        self.assertEqual(counts["summary"]["observed_bins"], 1)
        self.assertEqual(counts["summary"]["last_value"], 0)
        self.assertEqual(counts["summary"]["count_aggregation_total"], 0)
        cpu = tool._series(VM_ID, "cpu_percent", "platform_metrics", "Percentage CPU", "Percent",
                           {}, parameters()["window"], [dict(point)], "CPU", "native_metric_Count")
        self.assertEqual(cpu["summary"]["observed_bins"], 0)
        self.assertIsNone(cpu["summary"]["last_value"])

    def test_missing_memory_definition_stays_not_exposed(self):
        resource = inventory(VM_ID, "microsoft.compute/virtualmachines", "test-vm")[0]
        specs, absent = tool._metric_specs({"value": [definition()]}, resource, parameters()["window"], "all")
        self.assertEqual([spec["metric"] for spec in specs], ["cpu_percent"])
        self.assertTrue(any(item["metric"] == "memory_available_percent" for item in absent))

    def test_native_average_bins_do_not_invent_raw_peaks_or_weighting(self):
        resource = inventory(VM_ID, "microsoft.compute/virtualmachines", "test-vm")[0]
        specs, _ = tool._metric_specs({"value": [definition(aggregations=["Average"])]},
                                     resource, parameters()["window"], "cpu_percent")
        payload = {"interval": "PT5M", "value": [{
            "id": VM_ID + "/providers/Microsoft.Insights/metrics/Percentage CPU",
            "name": {"value": "Percentage CPU"}, "unit": "Percent",
            "timeseries": [{"data": [{"timeStamp": "2026-10-09T16:00:00Z", "average": 0},
                                     {"timeStamp": "2026-10-09T16:05:00Z"},
                                     {"timeStamp": "2026-10-09T16:10:00Z", "average": 90}]}],
        }]}
        result = tool._normalize_platform(payload, resource, specs, parameters()["window"])[0]
        self.assertEqual(result["summary"]["mean"], 45)
        self.assertIsNone(result["summary"]["maximum_observation"])
        self.assertEqual(result["summary"]["maximum_bin_mean"], 90)
        self.assertIsNone(result["summary"]["sample_count"])
        self.assertEqual(result["summary"]["observed_bins"], 2)

    def test_http_200_metric_error_is_not_success(self):
        resource = inventory(VM_ID, "microsoft.compute/virtualmachines", "test-vm")[0]
        specs, _ = tool._metric_specs({"value": [definition()]}, resource, parameters()["window"], "cpu_percent")
        with self.assertRaises(tool.EvidenceError):
            tool._normalize_platform({"interval": "PT5M", "value": [{
                "id": VM_ID + "/providers/Microsoft.Insights/metrics/Percentage CPU",
                "name": {"value": "Percentage CPU"}, "errorCode": "InvalidSamplingType",
                "unit": "Percent", "timeseries": [],
            }]}, resource, specs, parameters()["window"])


class SignalAndQueryTests(unittest.TestCase):
    def disk_series(self, mount, value=0):
        rows = [log_bin(value, timestamp=f"2026-10-09T16:{minute:02d}:00Z",
                        namespace="LogicalDisk", name="FreeSpacePercentage",
                        tags=json.dumps({"vm.azm.ms/mountId": mount})) for minute in (0, 5, 10)]
        series, _ = tool._normalize_guest(rows, "InsightsMetrics", WORKSPACE, inventory(), parameters()["window"])
        return series

    def test_canonical_snap_image_zero_keeps_data_without_writable_disk_pressure(self):
        series = self.disk_series("/snap/core20/2866")
        before = json.dumps(series, sort_keys=True)
        signals = tool._metric_signals(series)
        self.assertEqual(json.dumps(series, sort_keys=True), before)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["kind"], "package_image_capacity")
        self.assertEqual(signals[0]["severity"], "info")
        self.assertEqual(signals[0]["state"], "observed")
        self.assertEqual(signals[0]["evidence"]["writability"], "not_verified")
        self.assertEqual(signals[0]["evidence"]["observed_mean_free_percent"], 0)
        self.assertFalse(tool._review_actions(inventory(), signals),
                         "Package-image observations must not dominate writable-capacity owner actions.")

    def test_real_root_and_unexpected_mounts_remain_pressure_at_zero(self):
        for mount in ("/", "/data", "C:", "/snapshots/core20/2866", "/snap/core20/current",
                      "/snap/core20/x1", "/snap/core20/2866/data", "/custom/snap/core20/2866"):
            with self.subTest(mount=mount):
                signals = tool._metric_signals(self.disk_series(mount))
                self.assertTrue(any(row["kind"] == "sustained_pressure" and row["state"] == "review" for row in signals))
                self.assertFalse(any(row["kind"] == "package_image_capacity" for row in signals))

    def test_observed_root_headroom_is_not_a_full_disk_review(self):
        signals = tool._metric_signals(self.disk_series("/", 40.604))
        self.assertFalse(any(row["kind"] == "sustained_pressure" for row in signals))

    def test_long_native_alert_titles_are_preserved_and_wrap_without_overflow_masking(self):
        data = snapshot(resource_count=1)
        title = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{'long-resource-group-' * 10}/providers/Microsoft.Insights/metricAlerts/{'long-native-rule-' * 10}"
        data["events"] = [{"event_id": "test-native-event", "resource_id": ARC_ID,
                           "title": title, "time_utc": "2026-10-09T17:00:00Z", "severity": "warning",
                           "state": "review", "kind": "alert_fired", "source": "monitor_alerts", "details": title}]
        document = tool._json_document(data)
        restored = tool._unpack_snapshot(json.loads(document))
        self.assertEqual(restored["events"][0]["title"], title)
        markup = tool._render_html(data, document)
        self.assertIn(".event-list strong,.event-list .event-source,.event-list p{overflow-wrap:anywhere}", markup)
        self.assertIn(".review-row strong{min-width:0;overflow-wrap:anywhere}", markup)
        self.assertIn("${esc(e.title)}", markup)
        self.assertNotIn("body{overflow:hidden", markup)

    def test_identical_gaps_on_two_resources_have_distinct_evidence_ids(self):
        data = snapshot(resource_count=3)
        ids = [row["signal_id"] for row in data["signals"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_deliberate_deallocation_is_not_a_critical_outage(self):
        resource = inventory(VM_ID, "microsoft.compute/virtualmachines", "test-vm")[0]
        resource["health"] = {"availability_state": "Unavailable", "title": "Stopped and deallocated",
                              "reason_type": "Customer Initiated"}
        signals = tool._resource_signals([resource], [], [], [], REFERENCE, parameters()["window"])
        self.assertFalse(any(row["severity"] == "critical" for row in signals))
        self.assertTrue(any(row["kind"] == "stopped_without_samples" for row in signals))

    def test_focused_cpu_query_does_not_invent_an_unrequested_memory_gap(self):
        data = snapshot(metric_filter="cpu_percent")
        self.assertFalse(any("physical memory" in row["evidence"].get("missing_capabilities", []) for row in data["signals"]))

    def test_sparse_window_is_explicitly_unknown_not_healthy(self):
        data = snapshot(resource_count=1, metric_filter="cpu_percent")
        self.assertEqual(data["resources"][0]["assessment"], "unknown")
        self.assertTrue(any(row["kind"] == "telemetry_window_gap" for row in data["signals"]))

    def test_native_timeline_metric_association_cannot_be_invented(self):
        with self.assertRaises(tool.EvidenceError) as caught:
            parameters(view="timeline", metric="cpu_percent")
        self.assertEqual(caught.exception.code, "unsupported_filter")

    def test_rule_breaks_at_missing_bins_and_incomplete_edges(self):
        rows = [log_bin(90, timestamp="2026-10-09T16:00:00Z"),
                log_bin(90, timestamp="2026-10-09T16:05:00Z"),
                log_bin(90, timestamp="2026-10-09T16:15:00Z")]
        series, _ = tool._normalize_guest(rows, "InsightsMetrics", WORKSPACE, inventory(), parameters()["window"])
        self.assertFalse(any(row["kind"] == "sustained_pressure" for row in tool._metric_signals(series)))
        rows[2]["time_utc"] = "2026-10-09T16:10:00Z"
        rows[2]["first_sample_utc"] = rows[2]["time_utc"]
        rows[2]["last_sample_utc"] = "2026-10-09T16:10:04Z"
        series, _ = tool._normalize_guest(rows, "InsightsMetrics", WORKSPACE, inventory(), parameters()["window"])
        self.assertTrue(any(row["kind"] == "sustained_pressure" for row in tool._metric_signals(series)))

    def test_cpu_maximum_is_peak_evidence_not_raw_p95_or_native_alert(self):
        rows = [log_bin(40, minimum=10, maximum=100)]
        series, _ = tool._normalize_guest(rows, "InsightsMetrics", WORKSPACE, inventory(), parameters()["window"])
        signals = tool._metric_signals(series)
        peak = next(row for row in signals if row["kind"] == "cpu_peak")
        self.assertEqual(peak["state"], "observed")
        self.assertEqual(peak["severity"], "info")
        self.assertEqual(peak["evidence"]["maximum_source_observation"], 100)

    def test_mad_requires_prior_bins_and_preserves_percentage_point_delta(self):
        rows = [log_bin(2, timestamp=f"2026-10-09T16:{minute:02d}:00Z") for minute in range(0, 60, 5)]
        rows.append(log_bin(60, timestamp="2026-10-09T17:00:00Z"))
        series, _ = tool._normalize_guest(rows, "InsightsMetrics", WORKSPACE, inventory(), parameters()["window"])
        spikes = [row for row in tool._metric_signals(series) if row["kind"] == "statistical_spike"]
        self.assertEqual(len(spikes), 1)
        self.assertEqual(spikes[0]["evidence"]["prior_observed_bins"], 12)
        self.assertEqual(spikes[0]["evidence"]["delta_percent_points"], 58)

    def test_every_query_view_fits_default_serialization_and_pages_exactly(self):
        data = snapshot(resource_count=40)
        for view in tool.VIEWS:
            offset, seen, total = 0, 0, None
            while True:
                with self.subTest(view=view, offset=offset):
                    response = tool._query(data, parameters(view=view, offset=offset, limit=100))
                    self.assertLessEqual(len(json.dumps(response, allow_nan=False).encode()), 3500)
                    self.assertEqual(response["returned"], len(response["rows"]))
                    self.assertEqual(response["total_matched"], total if total is not None else response["total_matched"])
                    total = response["total_matched"]
                    seen += response["returned"]
                    if not response["has_more"]:
                        self.assertIsNone(response["next_offset"])
                        break
                    self.assertGreater(response["next_offset"], offset)
                    offset = response["next_offset"]
            self.assertEqual(seen, total, view)

    def test_codec_roundtrip_is_lossless_including_null_zero_and_timestamps(self):
        data = snapshot(resource_count=3)
        self.assertEqual(tool._unpack_snapshot(tool._pack_snapshot(data)), data)
        restored = tool._unpack_snapshot(json.loads(tool._json_document(data)))
        self.assertEqual(restored, data)

    def test_codec_two_preserves_missing_keys_numeric_types_and_nested_tables(self):
        data = snapshot(resource_count=1)
        data["source_records"] = [
            {"label": "same", "nested": {"value": True}, "value": 0, "nullable": None, "time": "2026-09-01T00:00:00Z"},
            {"label": "same", "nested": {"value": 1}, "value": 0.0, "time": "2026-09-01T01:00:00Z"},
            {"label": "same", "nested": {"value": 1.0}, "value": -0.0, "time": "2026-09-01T02:00:00Z"},
        ]
        encoded = tool._pack_snapshot(data)
        self.assertEqual(encoded["encoding_version"], "2.0")
        restored = tool._unpack_snapshot(encoded)
        self.assertEqual(json.dumps(restored, sort_keys=True), json.dumps(data, sort_keys=True))
        self.assertNotIn("nullable", restored["source_records"][1])
        self.assertEqual(struct.pack("<d", restored["source_records"][2]["value"]), struct.pack("<d", -0.0))

    def test_legacy_codec_one_remains_decodable(self):
        data = snapshot(resource_count=3)
        legacy = tool._pack_snapshot_v1(data)
        self.assertEqual(legacy["encoding_version"], "1.0")
        self.assertEqual(tool._unpack_snapshot(legacy), data)

    def test_codec_two_dense_float_column_is_binary_lossless(self):
        data = snapshot(resource_count=1)
        data["dense"] = [{"value": 0.000123456789 * (index + 0.123456789)} for index in range(300)]
        packed = tool._pack_snapshot(data)
        fields = packed["snapshot"][1]
        offset = fields.index(packed["strings"].index("dense"))
        table = fields[offset + 1]
        self.assertEqual(table[0], 3)
        self.assertEqual(table[3][0][0], 5)
        restored = tool._unpack_snapshot(packed)
        self.assertEqual(json.dumps(restored, sort_keys=True), json.dumps(data, sort_keys=True))

    def test_codec_two_rejects_invalid_columns_and_unknown_versions(self):
        data = snapshot(resource_count=1)
        packed = tool._pack_snapshot(data)
        packed["encoding_version"] = "99.0"
        with self.assertRaises(tool.EvidenceError):
            tool._unpack_snapshot(packed)
        for column in ([1, []], [2, [[2, 0]]], [3, None, [[2, 0]]], [5, "!", ""]):
            document = {
                "format": "infra-ops-columnar", "encoding_version": "2.0", "strings": ["series", "value"],
                "snapshot": [1, [0, [3, 1, [1], [column]]]],
            }
            with self.subTest(column=column), self.assertRaises(tool.EvidenceError):
                tool._unpack_snapshot(document)

    @unittest.skipUnless(shutil.which("node"), "Node is optional for the standalone decoder parity test.")
    def test_browser_decoder_matches_python_for_both_codec_versions(self):
        data = snapshot(resource_count=2)
        data["dense"] = [{"value": 0.000123456789 * (index + 0.123456789), "time": f"2026-09-01T{index % 24:02d}:00:00Z"}
                         for index in range(200)]
        data["safe_keys"] = [{"__proto__": {"polluted": "data only"}}, {"constructor": "data only", "missing": None}]
        decode = tool.REPORT_HTML.split("function decode(doc){", 1)[1].split("\nlet snapshot;", 1)[0]
        script = "function decode(doc){" + decode + "\nconst fs=require('node:fs');const input=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(decode(input)));"
        for document in (tool._pack_snapshot(data), tool._pack_snapshot_v1(data)):
            result = subprocess.run(["node", "-e", script], input=json.dumps(document), text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), data)

    def test_csv_formula_and_embedded_script_protection(self):
        self.assertEqual(tool._csv_cell(" =HYPERLINK(\"https://example.com\")"), "' =HYPERLINK(\"https://example.com\")")
        self.assertEqual(tool._csv_cell(0), 0)
        encoded = tool._safe_json(json.dumps({"name": "</script><script>alert(1)</script>\u2028"}, ensure_ascii=False))
        self.assertNotIn("</script>", encoded)
        self.assertEqual(json.loads(encoded)["name"], "</script><script>alert(1)</script>\u2028")

    def test_csv_exports_retain_snapshot_context(self):
        data = snapshot()
        rows = tool._csv_context(data, data["resources"])
        self.assertEqual(rows[0]["provenance"], data["provenance"])
        self.assertEqual(rows[0]["snapshot_collected_utc"], data["collected_utc"])
        self.assertEqual(rows[0]["window_start_utc"], data["window"]["start_utc"])
        self.assertEqual(rows[0]["window_end_utc"], data["window"]["end_utc"])


class ReadOnlyCollectorTests(unittest.TestCase):
    """Exercise the complete collector using synthetic, source-shaped HTTP replies."""

    def client(self, log_error=False, subscription_state="Enabled"):
        test = self

        class Client:
            def __init__(self):
                self.calls = []
                self.closed = False
                self.config = {"subscription_id": SUBSCRIPTION, "tenant_id": TENANT,
                               "client_id": CLIENT, "workspace_ids": [WORKSPACE]}

            def close(self):
                self.closed = True

            def table(self, rows):
                names = list(rows[0]) if rows else []
                return {"tables": [{"name": "PrimaryResult", "columns": [{"name": key, "type": "string"} for key in names],
                                    "rows": [[row[key] for key in names] for row in rows]}]}

            def request(self, method, url, source, body=None, deadline=None):
                tool._validate_endpoint(method, url, body, self.config)
                self.calls.append((method, url, source, body))
                if source == "subscription":
                    return {"subscriptionId": SUBSCRIPTION, "tenantId": TENANT, "state": subscription_state}
                if source == "inventory":
                    rows = [
                        {"id": ARC_ID, "name": "test-arc", "type": "microsoft.hybridcompute/machines",
                         "resourceGroup": "test-rg", "location": "test-region", "tags": {"Owner": "Synthetic owner"},
                         "properties": {"status": "Connected", "osType": "Linux"}},
                        {"id": VM_ID, "name": "test-vm", "type": "microsoft.compute/virtualmachines",
                         "resourceGroup": "test-rg", "location": "test-region", "tags": {},
                         "properties": {"powerState": "PowerState/deallocated", "osType": "Linux"}},
                    ]
                    test.assertEqual(body["subscriptions"], [SUBSCRIPTION])
                    test.assertEqual(body["query"], tool._inventory_query())
                    return {"data": rows, "count": 2, "totalRecords": 2, "resultTruncated": "false"}
                if source == "arc_extensions":
                    test.assertEqual(body["query"], tool._arc_extension_query())
                    test.assertIsNotNone(deadline)
                    return {"data": [], "count": 0, "totalRecords": 0, "resultTruncated": "false"}
                if source == "metric_definitions":
                    return {"value": [definition()]}
                if source == "platform_metrics":
                    return {"interval": "PT5M", "value": [{
                        "id": VM_ID + "/providers/Microsoft.Insights/metrics/Percentage CPU",
                        "name": {"value": "Percentage CPU"}, "unit": "Percent",
                        "timeseries": [{"metadatavalues": [], "data": [{"timeStamp": "2026-10-09T16:00:00Z"}]}],
                    }]}
                if source == "Heartbeat":
                    return self.table([{"resource_id": ARC_ID, "count": 100, "first_sample_utc": "2026-10-09T16:01:00Z",
                                        "last_sample_utc": "2026-10-09T17:58:00Z", "os_types": ["Linux"]}])
                if source == "Perf":
                    return self.table([])
                if source == "InsightsMetrics":
                    if log_error:
                        raise tool.EvidenceError("api_failed", "Synthetic Log Analytics denial.", source, 403)
                    rows = []
                    for hour, minute in ((hour, minute) for hour in (16, 17) for minute in range(0, 60, 5)):
                        timestamp = f"2026-10-09T{hour}:{minute:02d}:00Z"
                        rows.append(log_bin(2, timestamp=timestamp))
                        rows.append(log_bin(2048, timestamp=timestamp, namespace="Memory", name="AvailableMB",
                                            tags='{"vm.azm.ms/memorySizeMB":"4096"}'))
                    return self.table(rows)
                if source == "resource_health":
                    if "$skiptoken=second" in url:
                        return {"value": []}
                    return {
                        "value": [{"id": VM_ID + "/providers/Microsoft.ResourceHealth/availabilityStatuses/current",
                                   "properties": {"availabilityState": "Unavailable", "title": "Stopped and deallocated",
                                                  "reasonType": "Customer Initiated", "reportedTime": "2026-10-09T17:59:00Z"}}],
                        "nextLink": url + "&$skiptoken=second",
                    }
                if source == "monitor_alerts":
                    return {"value": []}
                test.fail("Unexpected source request: " + source)

        return Client()

    def test_full_collector_retains_arc_vm_insights_native_unknowns_and_pagination(self):
        client = self.client()
        with patch.object(tool, "AzureReadClient", return_value=client):
            data = tool._collect_live(client.config, parameters(), REFERENCE)
        self.assertTrue(client.closed)
        self.assertEqual(data["summary"]["resources"], 2)
        arc = next(row for row in data["resources"] if row["hosting"] == "arc")
        vm = next(row for row in data["resources"] if row["hosting"] == "azure")
        self.assertEqual(arc["assessment"], "observed")
        self.assertEqual(arc["arc_administration"]["baseline_status"], "not_configured")
        self.assertEqual(arc["arc_administration"]["assessment"], "unknown")
        self.assertEqual(arc["series_count"], 3)
        self.assertEqual(vm["assessment"], "unknown")
        self.assertEqual(vm["series_count"], 0)
        native = next(row for row in data["series"] if row["resource_id"] == VM_ID)
        self.assertIsNone(native["summary"]["mean"])
        self.assertEqual(native["summary"]["observed_bins"], 0)
        self.assertEqual(next(row["status"] for row in data["sources"] if row["source"] == "Perf"), "not_collected")
        self.assertEqual(next(row["pages"] for row in data["sources"] if row["source"] == "resource_health"), 2)
        self.assertFalse(any(row["severity"] == "critical" for row in data["signals"]))
        self.assertEqual(data["status"], "partial")
        for method, url, source, body in client.calls:
            with self.subTest(source=source):
                self.assertIn(method, ("GET", "POST"))
                if method == "POST":
                    self.assertTrue(source in ("inventory", "arc_extensions", "Heartbeat", "Perf", "InsightsMetrics"))
                if source in ("Heartbeat", "Perf", "InsightsMetrics"):
                    self.assertIn(WORKSPACE, url)
                    self.assertNotIn("workspaces", body, "Cross-workspace expansion must remain unavailable.")

    def test_log_failure_is_disclosed_without_erasing_independent_native_evidence(self):
        client = self.client(log_error=True)
        with patch.object(tool, "AzureReadClient", return_value=client):
            data = tool._collect_live(client.config, parameters(), REFERENCE)
        source = next(row for row in data["sources"] if row["source"] == "InsightsMetrics")
        self.assertEqual(source["status"], "error")
        self.assertEqual(source["error"]["http_status"], 403)
        self.assertTrue(any(row["source"] == "platform_metrics" for row in data["series"]))
        self.assertEqual(data["summary"]["source_errors"], 1)
        self.assertTrue(client.closed)

    def test_disabled_subscription_fails_before_inventory_or_telemetry_reads(self):
        client = self.client(subscription_state="Disabled")
        with patch.object(tool, "AzureReadClient", return_value=client), self.assertRaises(tool.EvidenceError):
            tool._collect_live(client.config, parameters(), REFERENCE)
        self.assertEqual([call[2] for call in client.calls], ["subscription"])
        self.assertTrue(client.closed)

    def test_complete_main_query_is_bounded_without_any_real_http_client(self):
        client = self.client()
        with patch.object(tool, "SUBSCRIPTION_ID", SUBSCRIPTION), patch.object(tool, "TENANT_ID", TENANT), \
             patch.object(tool, "MANAGED_IDENTITY_CLIENT_ID", CLIENT), patch.object(tool, "LOG_WORKSPACE_IDS", [WORKSPACE]), \
             patch.object(tool, "_utc_now", return_value=REFERENCE), patch.object(tool, "AzureReadClient", return_value=client):
            response = tool.main(operation="query", view="resources", period="last_2h")
        self.assertNotEqual(response["status"], "error")
        self.assertEqual(response["total_matched"], 2)
        self.assertLessEqual(tool._response_bytes(response), 3500)


class OperatorSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("bounded_operator", TOOL_PATH.parent / "controlled-cpu-load.py")
        cls.operator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.operator)

    def test_cli_help_is_valid_and_never_starts_workers(self):
        result = subprocess.run([sys.executable, str(TOOL_PATH.parent / "controlled-cpu-load.py"), "--help"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--baseline-only", result.stdout)
        self.assertIn("--target-cpu-percent", result.stdout)

    def test_signal_handler_has_no_locking_io_or_function_calls(self):
        tree = ast.parse(inspect.getsource(self.operator))
        handlers = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "request_stop"]
        self.assertEqual(len(handlers), 1)
        self.assertFalse(any(isinstance(node, ast.Call) for node in ast.walk(handlers[0])),
                         "Signal handlers must set only a local boolean, never acquire an Event/condition lock.")

    def test_worker_hot_loop_has_no_shared_event_polling(self):
        tree = ast.parse(inspect.getsource(self.operator._worker))
        outer = next(node for node in ast.walk(tree) if isinstance(node, ast.While))
        inner = next(node for node in ast.walk(outer) if isinstance(node, ast.While) and node is not outer)
        calls = [node for node in ast.walk(inner) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
        self.assertFalse(any(node.func.attr in ("is_set", "wait", "set") for node in calls),
                         "Shared Event synchronization must remain outside the <=0.1 second CPU-work loop.")

    @unittest.skipUnless(sys.platform.startswith("linux"), "Real Linux SIGTERM delivery is a parent runtime check on Windows.")
    def test_linux_sigterm_during_real_event_wait_exits_without_workers(self):
        script = """
import importlib.util, multiprocessing, signal, sys, time
from unittest.mock import patch
spec = importlib.util.spec_from_file_location("operator_signal_test", sys.argv[1])
operator = importlib.util.module_from_spec(spec); spec.loader.exec_module(operator)
real = multiprocessing.get_context("spawn")
class Event:
    def __init__(self):
        self.event = real.Event()
        original_wait = self.event._cond.wait
        def wait_with_lock_held(seconds=None):
            print("WAITING", flush=True)
            time.sleep(0.25)
            return original_wait(seconds)
        self.event._cond.wait = wait_with_lock_held
    def wait(self, seconds):
        return self.event.wait(seconds)
    def set(self):
        return self.event.set()
    def is_set(self):
        return self.event.is_set()
class Context:
    def Event(self):
        return Event()
    def Value(self, kind, value):
        return real.Value(kind, value)
    def Process(self, *args, **kwargs):
        raise AssertionError("Baseline-only regression must never create CPU workers.")
with patch.object(operator.sys, "argv", ["load", "--approved-host", "test-guest", "--workers", "1", "--baseline-only"]), \\
     patch.object(operator.socket, "gethostname", return_value="test-guest"), \\
     patch.object(operator.os, "cpu_count", return_value=1), \\
     patch.object(operator, "_cpu_sample", return_value=(1000, 900)), \\
     patch.object(operator.multiprocessing, "get_context", return_value=Context()):
    raise SystemExit(operator.main())
"""
        process = subprocess.Popen([sys.executable, "-c", script, str(TOOL_PATH.parent / "controlled-cpu-load.py")],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "WAITING")
            process.send_signal(self.operator.signal.SIGTERM)
            output, errors = process.communicate(timeout=8)
            self.assertEqual(process.returncode, 0, errors)
            self.assertIn('"workers_started": 0', output)
            self.assertIn('"status": "cancelled"', output)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=3)

    def test_load_needs_exact_host_acknowledgement_and_bounds(self):
        self.operator.validate_target("test-guest", "test-guest", True, 2, 360, 2)
        for values in (
            ("other-host", "test-guest", True, 2, 360, 2),
            ("test-guest", "test-guest", False, 2, 360, 2),
            ("test-guest", "test-guest", True, 3, 360, 2),
            ("test-guest", "test-guest", True, 2, 481, 2),
            ("test-guest", "test-guest", True, True, 360, 2),
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.operator.validate_target(*values)

    def test_eight_minute_limit_is_inclusive(self):
        self.operator.validate_target("test-guest", "test-guest", True, 2, 480, 2)
        self.assertEqual(self.operator.MAX_SECONDS, 480)

    def test_linux_baseline_parser_does_not_double_count_guest_ticks(self):
        counters = self.operator.parse_cpu_stat("cpu 100 0 50 800 50 0 0 0 25 0\ncpu0 1 2 3")
        self.assertEqual(counters, (1000, 850))
        self.assertEqual(self.operator.cpu_percent((1000, 850), (1200, 880)), 85.0)
        for previous, current in (((1000, 850), (1000, 850)), ((1000, 850), (900, 800)),
                                  ((1000, 850), (1100, 1000))):
            with self.subTest(current=current), self.assertRaises(ValueError):
                self.operator.cpu_percent(previous, current)

    def test_linux_memory_has_no_success_shaped_free_memory_fallback(self):
        self.assertEqual(self.operator.available_memory_bytes("MemAvailable: 1048576 kB\n"), 1024 ** 3)
        with self.assertRaises(ValueError):
            self.operator.available_memory_bytes("MemFree: 1048576 kB\n")

    def test_preflight_rejects_unvalidated_os_busy_hosts_low_memory_and_unreachable_target(self):
        self.operator.validate_preflight("Linux", 2, 1024 ** 3, 2, 82, 2)
        for values in (("Windows", 2, 1024 ** 3, 2, 82, 2),
                       ("Linux", 21, 1024 ** 3, 2, 82, 2),
                       ("Linux", 2, 100 * 1024 ** 2, 2, 82, 2),
                       ("Linux", 2, 1024 ** 3, 2, 85, 2),
                       ("Linux", 2, 1024 ** 3, 2, 82, 32)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.operator.validate_preflight(*values)

    def test_read_only_cgroup_hierarchy_uses_the_smallest_actual_quota(self):
        values = {
            "/sys/fs/cgroup/system.slice/run-test.scope/cpu.max": "30000 100000",
            "/sys/fs/cgroup/system.slice/cpu.max": "max 100000",
        }
        budget = self.operator.cgroup_budget(
            "0::/system.slice/run-test.scope\n",
            "29 24 0:26 / /sys/fs/cgroup rw,nosuid,nodev,noexec - cgroup2 cgroup rw",
            lambda path: values[path],
        )
        self.assertEqual(budget["quota_cores"], 0.3)
        self.assertEqual(len(budget["inspected_hierarchy"]), 2)
        self.assertFalse(budget["limits_changed"])
        values["/sys/fs/cgroup/system.slice/cpu.max"] = "20000 100000"
        restricted = self.operator.cgroup_budget(
            "0::/system.slice/run-test.scope\n",
            "29 24 0:26 / /sys/fs/cgroup rw - cgroup2 cgroup rw",
            lambda path: values[path],
        )
        self.assertEqual(restricted["quota_cores"], 0.2)

    def test_arc_quota_accepts_14_host_percent_and_rejects_72_without_workers(self):
        budget = {"quota_cores": 0.3, "affinity_cpus": 2}
        self.operator.validate_preflight("Linux", 1.0, 1024 ** 3, 2, 14, 2, budget)
        with self.assertRaises(self.operator.UnreachableTargetError):
            self.operator.validate_preflight("Linux", 1.0, 1024 ** 3, 2, 72, 2, budget)
        with self.assertRaises(self.operator.UnreachableTargetError):
            self.operator.validate_preflight("Linux", 1.0, 1024 ** 3, 2, 72, 2,
                                             {"quota_cores": None, "affinity_cpus": 1})

    def test_uninspectable_cpu_governance_is_not_treated_as_unlimited(self):
        for membership, mountinfo in (
            ("1:cpu:/system.slice/run-test.scope", "29 24 0:26 / /sys/fs/cgroup rw - cgroup cgroup rw"),
            ("0::/system.slice/run-test.scope", "29 24 0:26 /hidden /sys/fs/cgroup rw - cgroup2 cgroup rw"),
            ("0::/../escape", "29 24 0:26 / /sys/fs/cgroup rw - cgroup2 cgroup rw"),
            ("0::/system.slice/run-test.scope", ""),
        ):
            with self.subTest(membership=membership, mountinfo=mountinfo), self.assertRaises(ValueError):
                self.operator.cgroup_budget(membership, mountinfo, lambda path: "max 100000")
        for value in ("0 100000", "-1 100000", "max 0", "30000", "nan 100000"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.operator.parse_cpu_max(value)
        self.assertIsNone(self.operator.parse_cpu_max("max 100000"))

    def test_feedback_caps_duty_and_aborts_above_sampled_host_ceiling(self):
        self.assertEqual(self.operator.adjusted_duty(0.84, 1, 82, 2, 2), 0.85)
        self.assertEqual(self.operator.adjusted_duty(0.01, 84, 1, 2, 2), 0.0)
        with self.assertRaises(ValueError):
            self.operator.adjusted_duty(0.80, 85.01, 82, 2, 2)

    def simulated_run(self, *, baseline_only=False, high_sample=False, signal_after_baseline=False,
                      quota_cores=None, target=82, low_samples=False):
        """Run main with a synthetic clock/process context; no actual worker or load."""
        operator = self.operator

        class Clock:
            seconds = 0.0

            def monotonic(self):
                return self.seconds

        clock = Clock()
        handlers = {}
        created = []

        class Event:
            stopped = False
            waits = 0
            waiting = False

            def is_set(self):
                return self.stopped

            def set(self):
                if self.waiting:
                    raise RuntimeError("Synthetic non-reentrant Event lock would deadlock in signal handler.")
                self.stopped = True

            def wait(self, duration):
                self.waits += 1
                clock.seconds += duration
                if signal_after_baseline and self.waits == 2:
                    self.waiting = True
                    handlers[operator.signal.SIGTERM](operator.signal.SIGTERM, None)
                    self.waiting = False
                return self.stopped

        stop = Event()

        class Duty:
            def __init__(self, _kind, value):
                self.value = value

        class Process:
            def __init__(self, target, args, daemon):
                self.pid = 2000 + len(created)
                self.target, self.args, self.daemon = target, args, daemon
                self.started = False
                self.finished = False
                created.append(self)

            def start(self):
                self.started = True

            def is_alive(self):
                return self.started and not self.finished and not stop.is_set() and clock.seconds < self.args[0]

            def join(self, timeout):
                self.finished = True

        class Context:
            def Event(self):
                return stop

            Value = Duty

            def Process(self, target, args, daemon):
                return Process(target, args, daemon)

        calls = []

        def sample():
            calls.append(clock.seconds)
            if len(calls) == 1:
                return 10000, 9000
            if len(calls) in (2, 3):
                return 13000, 11940
            elapsed = clock.seconds - 3
            idle_per_second = 100 if high_sample else 990 if low_samples else 180
            return 13000 + int(elapsed * 1000), 11940 + int(elapsed * idle_per_second)

        args = ["controlled-cpu-load.py", "--approved-host", "test-guest", "--workers", "2",
                "--duration-seconds", "6", "--target-cpu-percent", str(target), "--acknowledge-risk"]
        if baseline_only:
            args.append("--baseline-only")
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(operator.sys, "argv", args), patch.object(operator.platform, "system", return_value="Linux"), \
             patch.object(operator.socket, "gethostname", return_value="test-guest"), \
             patch.object(operator.os, "cpu_count", return_value=2), patch.object(operator, "_cpu_sample", side_effect=sample), \
             patch.object(operator, "_memory_sample", return_value=1024 ** 3), \
             patch.object(operator, "_cpu_budget", return_value={"quota_cores": quota_cores, "affinity_cpus": 2,
                                                                "limits_changed": False}), \
             patch.object(operator.multiprocessing, "get_context", return_value=Context()), \
             patch.object(operator.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(operator.signal, "signal", side_effect=lambda key, handler: handlers.__setitem__(key, handler)), \
             redirect_stdout(output), redirect_stderr(errors):
            exit_code = operator.main()
        return exit_code, [json.loads(line) for line in output.getvalue().splitlines()], \
            [json.loads(line) for line in errors.getvalue().splitlines()], created, stop

    def test_baseline_only_creates_no_processes(self):
        code, output, errors, children, _ = self.simulated_run(baseline_only=True)
        self.assertEqual(code, 0)
        self.assertFalse(children)
        self.assertFalse(errors)
        self.assertEqual(output[0]["status"], "baseline")
        self.assertTrue(output[0]["baseline_only"])

    def test_independent_deadline_cleans_all_simulated_workers(self):
        code, output, errors, children, stop = self.simulated_run()
        self.assertEqual(code, 0)
        self.assertFalse(errors)
        self.assertTrue(all(child.finished for child in children))
        self.assertTrue(stop.is_set())
        self.assertEqual(output[-1]["reason"], "deadline")
        self.assertTrue(output[-1]["all_workers_stopped"])
        self.assertTrue(all(child.args[2].value <= 0.85 for child in children))
        self.assertTrue(output[-1]["target_achieved"])

    def test_sampled_cpu_abort_reports_error_and_cleans_workers(self):
        code, output, errors, children, stop = self.simulated_run(high_sample=True)
        self.assertEqual(code, 1)
        self.assertEqual(errors[0]["code"], "load_safety_abort")
        self.assertEqual(output[-1]["reason"], "safety_abort")
        self.assertTrue(all(child.finished for child in children))
        self.assertTrue(stop.is_set())

    def test_sigterm_trap_cleans_only_created_simulated_workers(self):
        code, output, errors, children, stop = self.simulated_run(signal_after_baseline=True)
        self.assertEqual(code, 0)
        self.assertFalse(errors)
        self.assertEqual(output[-1]["reason"], "operator_signal")
        self.assertTrue(all(child.finished for child in children))
        self.assertTrue(stop.is_set())

    def test_unreachable_quota_fails_explicitly_before_creating_workers(self):
        code, output, errors, children, stop = self.simulated_run(quota_cores=0.3, target=72)
        self.assertEqual(code, 1)
        self.assertFalse(children)
        self.assertEqual(errors[0]["code"], "unreachable_target")
        self.assertTrue(stop.is_set())
        self.assertFalse(output[-1]["target_achieved"])

    def test_deadline_without_achieved_target_is_failure_despite_successful_cleanup(self):
        code, output, errors, children, stop = self.simulated_run(low_samples=True)
        self.assertEqual(code, 1)
        self.assertEqual(errors[0]["code"], "unreachable_target")
        self.assertFalse(output[-1]["target_achieved"])
        self.assertTrue(output[-1]["all_workers_stopped"])
        self.assertTrue(all(child.finished for child in children))


class ArtifactStorageTests(unittest.TestCase):
    def native_paths(self, root):
        stem = "infra-20261010T111304Z-48e86d8d"
        directory = root / "infrastructure-operations-reports"
        return {
            "report_path": directory / (stem + ".html"),
            "resources_csv_path": directory / (stem + "-resources.csv"),
            "signals_csv_path": directory / (stem + "-signals.csv"),
            "snapshot_path": directory / (stem + "-snapshot.json"),
        }

    def test_native_aliases_derive_only_from_the_recognized_guarded_runtime_root(self):
        thread = "55555555-5555-4555-8555-555555555555"
        root = PurePosixPath("/root/sreagent/terminalRoot/tmp/ThreadFiles") / thread
        paths = self.native_paths(root)
        fields = tool._sharing_fields(root, paths)
        self.assertEqual(fields["sharing_mode"], "native_ui")
        self.assertFalse(fields["http_verified"])
        for key, path in paths.items():
            alias = fields[key.removesuffix("_path") + "_url"]
            self.assertEqual(alias, "/api/files/tmp/ThreadFiles/" + thread + "/infrastructure-operations-reports/" + path.name)
            self.assertFalse(alias.startswith(("http:", "https:", "sandbox:")))

    def test_unknown_windows_and_neighbor_roots_expose_local_paths_without_fictitious_urls(self):
        for root in (
            PureWindowsPath(r"C:\Users\test\reports"),
            PurePosixPath("/tmp/ThreadFiles/55555555-5555-4555-8555-555555555555"),
            PurePosixPath("/root/sreagent/terminalRoot/tmp/ThreadFiles/not-a-thread"),
            PurePosixPath("/root/sreagent/terminalRoot/tmp/ThreadFiles/55555555-5555-4555-8555-555555555555/extra"),
        ):
            with self.subTest(root=root):
                fields = tool._sharing_fields(root, self.native_paths(root))
                self.assertEqual(fields, {"sharing_mode": "local_files_only", "http_verified": False})

    def test_native_alias_never_escapes_to_a_different_directory_or_injected_filename(self):
        root = PurePosixPath("/root/sreagent/terminalRoot/tmp/ThreadFiles/55555555-5555-4555-8555-555555555555")
        for path in (root / "other-directory" / "report.html",
                     root / "infrastructure-operations-reports" / "malicious%2Fescape.html",
                     root / "infrastructure-operations-reports" / "report?token=secret.html"):
            paths = self.native_paths(root)
            paths["report_path"] = path
            with self.subTest(path=path), self.assertRaises(tool.EvidenceError):
                tool._sharing_fields(root, paths)

    def test_all_four_actual_paths_and_native_aliases_fit_default_transport_without_truncation(self):
        root = PurePosixPath("/root/sreagent/terminalRoot/tmp/ThreadFiles/55555555-5555-4555-8555-555555555555")
        paths = self.native_paths(root)
        response = tool._envelope(snapshot(resource_count=40))
        response.update({key: str(path) for key, path in paths.items()})
        response.update(tool._sharing_fields(root, paths))
        response.update(artifact_status="written", top_review_resources=[], actions_total=40,
                        actions_returned=0, actions_has_more=True)
        tool._budget(response)
        self.assertLessEqual(len(json.dumps(response).encode("utf-8")), 3500)
        self.assertEqual(len([key for key in response if key.endswith("_path")]), 4)
        self.assertEqual(len([key for key in response if key.endswith("_url")]), 4)
        self.assertEqual(response["status"], "partial")
        self.assertEqual(response["sharing_mode"], "native_ui")
        for key, path in paths.items():
            self.assertEqual(response[key], str(path))

    def test_real_4800000_byte_boundary_is_inclusive_and_never_truncates(self):
        data = snapshot()
        with tempfile.TemporaryDirectory(prefix="case03-test-") as temporary:
            root = Path(temporary)
            with patch.object(tool.Path, "cwd", return_value=root), \
                 patch.object(tool, "_render_html", return_value="x" * 4_800_000, create=True):
                response = tool._write_report(data)
            self.assertEqual(Path(response["report_path"]).stat().st_size, 4_800_000)
        with tempfile.TemporaryDirectory(prefix="case03-test-") as temporary:
            root = Path(temporary)
            with patch.object(tool.Path, "cwd", return_value=root), \
                 patch.object(tool, "_render_html", return_value="x" * 4_800_001, create=True):
                with self.assertRaises(tool.EvidenceError):
                    tool._write_report(data)
            self.assertFalse((root / "infrastructure-operations-reports").exists())

    def test_four_actual_paths_and_complete_snapshot_fit_default_transport(self):
        data = snapshot()
        with tempfile.TemporaryDirectory(prefix="case03-test-") as temporary:
            with patch.object(tool.Path, "cwd", return_value=Path(temporary)), patch.object(tool, "_render_html", return_value="<!doctype html><title>TEST ONLY</title>", create=True):
                response = tool._write_report(data)
            self.assertLessEqual(len(json.dumps(response).encode()), 3500)
            self.assertEqual(response["artifact_status"], "written")
            self.assertEqual(response["sharing_mode"], "local_files_only")
            self.assertFalse(response["http_verified"])
            for key in ("report_path", "resources_csv_path", "signals_csv_path", "snapshot_path"):
                path = Path(response[key])
                self.assertEqual(path.parent, Path(temporary).resolve() / "infrastructure-operations-reports")
                self.assertTrue(path.is_file())
            document = json.loads(Path(response["snapshot_path"]).read_text(encoding="utf-8"))
            self.assertEqual(tool._unpack_snapshot(document), data)

    def test_exact_plain_byte_threshold_is_checked_before_any_write(self):
        data = snapshot()
        with tempfile.TemporaryDirectory(prefix="case03-test-") as temporary:
            root = Path(temporary)
            with patch.object(tool.Path, "cwd", return_value=root), patch.object(tool, "MAX_ARTIFACT_BYTES", 10), \
                 patch.object(tool, "_render_html", return_value="x" * 11, create=True):
                with self.assertRaises(tool.EvidenceError) as caught:
                    tool._write_report(data)
            self.assertEqual(caught.exception.code, "artifact_size_exceeded")
            self.assertFalse((root / "infrastructure-operations-reports").exists())

    def test_atomic_write_failure_cleans_only_its_partial_artifacts(self):
        data = snapshot()
        real_replace = os.replace
        calls = []

        def replace(source, destination):
            calls.append(destination)
            if len(calls) == 2:
                raise OSError("synthetic write failure")
            return real_replace(source, destination)

        with tempfile.TemporaryDirectory(prefix="case03-test-") as temporary:
            with patch.object(tool.Path, "cwd", return_value=Path(temporary)), \
                 patch.object(tool, "_render_html", return_value="<html>TEST ONLY</html>", create=True), \
                 patch.object(tool.os, "replace", side_effect=replace):
                with self.assertRaises(tool.EvidenceError) as caught:
                    tool._write_report(data)
            self.assertEqual(caught.exception.code, "artifact_write_failed")
            self.assertFalse(caught.exception.artifacts_may_remain)
            self.assertEqual(list((Path(temporary) / "infrastructure-operations-reports").iterdir()), [])

    def test_fixed_directory_cannot_be_overridden(self):
        with patch.object(tool, "OUTPUT_DIRECTORY", Path("other-directory")), self.assertRaises(tool.EvidenceError):
            tool._artifact_directory()

    def test_cleanup_failure_is_not_a_false_no_artifacts_claim(self):
        error = tool.EvidenceError("artifact_write_failed", "Cleanup failed.", "artifact_storage", artifacts_may_remain=True)
        response = tool._failure(error)
        self.assertIsNone(response["artifacts_created"])
        self.assertTrue(response["artifacts_may_remain"])

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="case03-test-") as temporary:
            root = Path(temporary)
            inside, outside = root / "inside", root / "outside"
            inside.mkdir()
            outside.mkdir()
            try:
                (inside / "infrastructure-operations-reports").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest("This Windows user cannot create symlinks: " + type(exc).__name__)
            with patch.object(tool.Path, "cwd", return_value=inside), self.assertRaises(tool.EvidenceError):
                tool._artifact_directory()


if __name__ == "__main__":
    unittest.main()
