"""Parameters, chat views, files, native sharing and configuration errors (offline)."""

import csv
import io
import json
import os
import tempfile
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath

from support import NOW, SUB, at, load_tool, row, snapshot

THREAD = "55555555-5555-4555-8555-555555555555"


def demo_rows(count=0):
    rows = [row("microsoft.network/networksecuritygroups", "nsg-app", changes={
        "properties.securityRules[0].name": ("", "allow-rdp"), "properties.securityRules[0].properties.access": ("", "Allow"),
        "properties.securityRules[0].properties.direction": ("", "Inbound"),
        "properties.securityRules[0].properties.sourceAddressPrefix": ("", "Internet"),
        "properties.securityRules[0].properties.destinationPortRange": ("", "3389")}, ts=at(1)),
        row("microsoft.network/publicipaddresses", "pip1", "Delete", ts=at(2)),
        row("microsoft.compute/disks", "disk1", changes={"properties.diskSizeGB": ("4", "8")}, ts=at(3)),
        row("microsoft.web/sites", "=HYPERLINK(\"x\")", changes={"tags.owner": ("", "-cmd")}, ts=at(4))]
    rows += [row("microsoft.web/sites", f"app-{i:03d}-with-a-rather-long-name", changes={"properties.siteConfig.alwaysOn": ("true", "false")},
                 ts=at(5 + i)) for i in range(count)]
    return rows


class ParameterTests(unittest.TestCase):
    def setUp(self):
        self.t = load_tool()

    def test_defaults_and_window(self):
        p = self.t.validate_parameters(now=NOW)
        self.assertEqual((p["operation"], p["period"], p["min_level"], p["view"], p["limit"]), ("report", "last_24h", "medium", "summary", 25))
        self.assertEqual((p["window"]["start_utc"], p["window"]["end_utc"]), ("2026-11-05T18:00:00Z", "2026-11-06T18:00:00Z"))
        self.assertEqual(self.t.validate_parameters(period="last_14d", now=NOW)["window"]["start_utc"], "2026-10-23T18:00:00Z")

    def test_invalid_values_are_rejected_with_clear_codes(self):
        cases = [dict(operation="delete"), dict(period="last_30d"), dict(min_level="critical"), dict(view="kql"),
                 dict(operation="query", limit=0), dict(operation="query", limit=101), dict(operation="query", limit="abc"),
                 dict(operation="query", limit=True), dict(resource_group="rg'; drop"), dict(resource_group="a/b"),
                 dict(resource_group="x" * 91)]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(self.t.DigestError) as raised:
                self.t.validate_parameters(now=NOW, **kwargs)
            self.assertEqual(raised.exception.code, "invalid_parameter")

    def test_report_rejects_query_only_parameters(self):
        for kwargs in (dict(view="deletes"), dict(limit=10)):
            with self.subTest(kwargs=kwargs), self.assertRaises(self.t.DigestError) as raised:
                self.t.validate_parameters(operation="report", now=NOW, **kwargs)
            self.assertEqual(raised.exception.code, "invalid_combination")

    def test_tolerant_but_validated_inputs(self):
        p = self.t.validate_parameters(operation=" Query ", period="LAST_7D", view="Relevant", limit="10", resource_group=" rg-app ", now=NOW)
        self.assertEqual((p["operation"], p["period"], p["view"], p["limit"], p["resource_group"]), ("query", "last_7d", "relevant", 10, "rg-app"))
        self.assertEqual(self.t.validate_parameters(None, None, None, None, None, None, now=NOW)["period"], "last_24h")


class ConfigurationTests(unittest.TestCase):
    def test_placeholders_return_a_clear_error_and_never_crash(self):
        t = load_tool(configure=False)
        result = t.main()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "configuration_required")
        self.assertIn("MANAGED_IDENTITY_CLIENT_ID", result["error"]["message"])
        t.MANAGED_IDENTITY_CLIENT_ID = "12345678-1234-4abc-8def-123456789abc"
        result = t.main(operation="query")
        self.assertEqual(result["error"]["code"], "configuration_required")
        self.assertIn("<YOUR_SUBSCRIPTION_ID>", result["error"]["message"])
        self.assertLessEqual(len(json.dumps(result)), t.TRANSPORT_BYTES)

    def test_management_group_scope_allows_the_subscription_placeholder(self):
        t = load_tool(configure=False)
        t.MANAGED_IDENTITY_CLIENT_ID = "12345678-1234-4abc-8def-123456789abc"
        t.MANAGEMENT_GROUP_ID = "mg-contoso"
        config = t.validate_config()
        self.assertEqual((config["subscriptions"], t.scope_chunks(config)), ([], [{"managementGroups": ["mg-contoso"]}]))

    def test_invalid_parameters_are_reported_before_configuration(self):
        result = load_tool(configure=False).main(period="yesterday")
        self.assertEqual(result["error"]["code"], "invalid_parameter")

    def test_bad_config_values_are_rejected(self):
        for name, value in (("EXCLUDED_RESOURCE_GROUPS", ["(?=x)"]), ("EXCLUDED_RESOURCE_GROUPS", ["a'b"]), ("BUSINESS_HOURS", (20, 8)),
                            ("OUTPUT_DIRECTORY", "../out"), ("EXCLUDED_RESOURCE_TYPES", ["not a type"]), ("MAX_COLLECTION_SECONDS", 500)):
            t = load_tool()
            setattr(t, name, value)
            with self.subTest(name=name), self.assertRaises(t.DigestError) as raised:
                t.validate_config()
            self.assertEqual(raised.exception.code, "configuration_required")


class QueryViewTests(unittest.TestCase):
    def setUp(self):
        self.t = load_tool()

    def test_every_view_fits_the_transport_budget_and_honours_limit(self):
        snap, _ = snapshot(self.t, demo_rows(150), min_level="low")
        for view in self.t.VIEWS:
            for limit in (1, 5, 100):
                p = self.t.validate_parameters(operation="query", view=view, limit=limit, min_level="low", now=NOW)
                result = self.t.query_view(snap, p)
                with self.subTest(view=view, limit=limit):
                    self.assertLessEqual(len(json.dumps(result).encode("utf-8")), self.t.TRANSPORT_BYTES)
                    self.assertLessEqual(len(result.get("rows", result.get("top_items", []))), limit)
                    self.assertEqual((result["operation"], result["view"]), ("query", view))
        p = self.t.validate_parameters(operation="query", view="relevant", limit=100, min_level="low", now=NOW)
        result = self.t.query_view(snap, p)
        self.assertTrue(result["transport_capped"])
        self.assertGreater(result["total_matched"], result["returned"])
        self.assertIn("note", result)

    def test_relevant_view_respects_min_level(self):
        snap, _ = snapshot(self.t, demo_rows(3), min_level="low")
        high = self.t.query_view(snap, self.t.validate_parameters(operation="query", view="relevant", min_level="high", now=NOW))
        self.assertTrue(high["rows"])
        self.assertTrue(all(r["level"] == "high" for r in high["rows"]))


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.t = load_tool()

    def test_csv_injection_guard(self):
        for value, expected in (("=1+1", "'=1+1"), ("+cmd", "'+cmd"), ("-2", "'-2"), ("@SUM(A1)", "'@SUM(A1)"), ("\tx", "'\tx"),
                                ("  =x", "'  =x"), ("plain", "plain"), (True, "yes"), (None, ""), (["a", "=b"], "a | =b")):
            with self.subTest(value=value):
                self.assertEqual(self.t.csv_cell(value), expected)
        document = self.t.csv_document([{"a": "=HYPERLINK(1)", "b": 'x,"y"'}], ("a", "b"))
        self.assertEqual(list(csv.reader(io.StringIO(document)))[1], ["'=HYPERLINK(1)", 'x,"y"'])

    def test_output_file_names_are_guarded(self):
        directory = Path("out") / "change-digest-reports"
        good = self.t.artifact_paths(directory, "change-digest-20261106T180000Z-0123abcd")
        self.assertEqual(sorted(p.name for p in good.values()), sorted(["change-digest-20261106T180000Z-0123abcd.html",
                         "change-digest-20261106T180000Z-0123abcd-snapshot.json", "change-digest-20261106T180000Z-0123abcd-changes.csv",
                         "change-digest-20261106T180000Z-0123abcd-property-diffs.csv"]))
        for stem in ("../change-digest-20261106T180000Z-0123abcd", "change-digest-x", "report?token=1", "change-digest-20261106T180000Z-0123ABCD"):
            with self.subTest(stem=stem), self.assertRaises(self.t.DigestError) as raised:
                self.t.artifact_paths(directory, stem)
            self.assertEqual(raised.exception.code, "unsafe_filename")

    def test_native_sharing_links_use_the_thread_files_alias(self):
        for prefix in ("/root/sreagent/terminalRoot/tmp/ThreadFiles", "/usr/terminalRoot/tmp/ThreadFiles"):
            root = PurePosixPath(prefix) / THREAD
            paths = self.t.artifact_paths(root / "change-digest-reports", "change-digest-20261106T180000Z-0123abcd")
            fields = self.t.sharing_fields(root, paths)
            with self.subTest(prefix=prefix):
                self.assertEqual(fields["sharing_mode"], "native_ui")
                self.assertEqual(fields["report_url"], f"/api/files/tmp/ThreadFiles/{THREAD}/change-digest-reports/change-digest-20261106T180000Z-0123abcd.html")
                self.assertEqual(sorted(k for k in fields if k.endswith("_url")), ["changes_csv_url", "diffs_csv_url", "report_url", "snapshot_url"])

    def test_no_aliases_outside_the_sandbox_and_no_escape(self):
        for root in (PureWindowsPath(r"C:\work"), PurePosixPath("/tmp/ThreadFiles") / THREAD, PurePosixPath("/usr/terminalRoot/tmp/ThreadFiles/not-a-guid")):
            paths = self.t.artifact_paths(Path("x"), "change-digest-20261106T180000Z-0123abcd")
            self.assertEqual(self.t.sharing_fields(root, paths), {"sharing_mode": "local_files_only"})
        root = PurePosixPath("/root/sreagent/terminalRoot/tmp/ThreadFiles") / THREAD
        paths = self.t.artifact_paths(root / "other-folder", "change-digest-20261106T180000Z-0123abcd")
        with self.assertRaises(self.t.DigestError) as raised:
            self.t.sharing_fields(root, paths)
        self.assertEqual(raised.exception.code, "unsafe_sharing_path")

    def test_write_report_writes_four_offline_files_and_a_compact_answer(self):
        snap, _ = snapshot(self.t, demo_rows(40))
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as folder:
            os.chdir(folder)
            try:
                result = self.t.write_report(snap)
                files = sorted(Path(folder, "change-digest-reports").iterdir())
                html_text = Path(result["report_path"]).read_text(encoding="utf-8")
                saved = json.loads(Path(result["snapshot_path"]).read_text(encoding="utf-8"))
                changes_csv = Path(result["changes_csv_path"]).read_bytes()
                diffs = list(csv.DictReader(io.StringIO(Path(result["diffs_csv_path"]).read_text(encoding="utf-8-sig"))))
            finally:
                os.chdir(cwd)
        self.assertEqual(len(files), 4)
        self.assertEqual((result["status"], result["artifact_status"], result["sharing_mode"]), ("ok", "written", "local_files_only"))
        self.assertLessEqual(len(json.dumps(result).encode("utf-8")), self.t.TRANSPORT_BYTES)
        self.assertTrue(result["top_items"])
        self.assertLessEqual(len(result["top_items"]), 10)
        self.assertEqual(saved["schema"], "azure-change-digest/1")
        for key in ("window", "scope", "counts", "headline", "changes", "delete_chains", "role_assignments", "activity_log_gaps", "actors",
                    "unusual", "noise", "coverage", "sources"):
            self.assertIn(key, saved)
        self.assertTrue(changes_csv.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"'=HYPERLINK", changes_csv)
        self.assertTrue(any(d["path"] == "properties.diskSizeGB" and d["previous_value"] == "4" and d["new_value"] == "8" for d in diffs))
        self.assertTrue(any(d["new_value"] == "'-cmd" for d in diffs))
        self.assertNotRegex(html_text, r"<script[^>]+src=|<link[^>]+href=|@import|url\(\s*['\"]?https?:|<img[^>]+src=\"?https?:")
        self.assertIn("Relevant Azure changes", html_text)
        self.assertNotIn("=HYPERLINK(\"x\")<", html_text)
        for section in ("matters", "deletes", "security", "who", "clickops", "unusual", "noise", "all", "coverage"):
            self.assertIn(f'id="{section}"', html_text)

    def test_report_is_locked_down_and_print_ready(self):
        snap, _ = snapshot(self.t, demo_rows(2))
        snap["client_name"] = 'Contoso "</style><script>alert(1)</script>'
        page = self.t.render_html(snap)
        style = page[page.index("<style>") + len("<style>"):page.index("</style>")]
        self.assertIn("default-src 'none'", page)
        self.assertIn("data-print", page)
        self.assertIn("@page", style)
        self.assertNotIn("<", style)
        self.assertEqual(page.count("<script>"), 1)

    def test_very_large_estates_drop_low_level_detail_instead_of_failing(self):
        snap, _ = snapshot(self.t, demo_rows(150))
        full, note = self.t.build_documents(snap)
        self.assertIsNone(note)
        self.t.ARTIFACT_BYTES = max(len(v) for v in full.values()) - 1
        slim, note = self.t.build_documents(snap)
        self.assertIn("Low-level changes were omitted", note)
        saved = json.loads(slim["snapshot_path"])
        self.assertTrue(saved["changes"])
        self.assertTrue(all(c["level"] != "low" for c in saved["changes"]))
        self.assertEqual(saved["counts"], snap["counts"])
        self.t.ARTIFACT_BYTES = 1000
        with self.assertRaises(self.t.DigestError) as raised:
            self.t.build_documents(snap)
        self.assertEqual(raised.exception.code, "artifact_size_exceeded")

    def test_snapshot_counts_and_headline(self):
        snap, _ = snapshot(self.t, demo_rows(0), noise_types=[{"rtype": "microsoft.compute/disks", "rgKey": f"{SUB}/rg-app", "byType": "System",
                                                               "changes": 6, "agentChanges": 1}])
        counts = snap["counts"]
        self.assertEqual(counts["total"], 4 + 6)
        self.assertEqual(counts["by_level"]["noise"], 6)
        self.assertEqual(counts["noise_filtered_pct"], 60)
        self.assertEqual(counts["by_level"]["high"], 2)
        self.assertTrue(snap["headline"]["verdict"].startswith("3 relevant changes out of 10"))
        self.assertEqual(snap["noise"]["by_reason"], {"platform metadata/timestamp": 5, "agent-reported inventory": 1})


if __name__ == "__main__":
    unittest.main()
