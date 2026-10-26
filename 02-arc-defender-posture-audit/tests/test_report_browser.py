"""Opt-in real-browser checks. No Azure calls or runtime/download receipt claims."""

import copy
import csv
import hashlib
import io
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_arc_defender_tools import REFERENCE, live, sim
from test_artifact_encoding import (
    CURRENT_FIXTURE, expansion_documents, javascript_decoder, legacy_pack, malformed_documents,
    sparse_unused_default_document,
)


@unittest.skipUnless(os.environ.get("SRE_REPORT_BROWSER_TESTS") == "1",
                     "Set SRE_REPORT_BROWSER_TESTS=1 to use installed Playwright and a local browser.")
class ReportBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(
            headless=True, **({"channel": "msedge"} if sys.platform == "win32" else {})
        )
        cls.addClassCleanup(cls.browser.close)

    def download(self, page, selector):
        with page.expect_download() as pending:
            page.locator(selector).click()
        return Path(pending.value.path()).read_bytes()

    def csv_rows(self, content):
        previous = csv.field_size_limit()
        try:
            csv.field_size_limit(max(previous, len(content)))
            return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
        finally:
            csv.field_size_limit(previous)

    def check_report(self, snapshot, tool):
        with tempfile.TemporaryDirectory() as folder, patch.object(tool.Path, "cwd", return_value=Path(folder)):
            result = tool._write_report(snapshot)
            context = self.browser.new_context(accept_downloads=True, viewport={"width": 1440, "height": 1000})
            self.addCleanup(context.close)
            page = context.new_page()
            errors, external = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: external.append(request.url)
                    if not request.url.startswith(("file:", "data:", "blob:")) else None)
            page.goto(Path(result["report_path"]).as_uri())
            self.assertTrue(page.evaluate("snapshot") == snapshot, "Browser full-snapshot field mismatch.")
            self.assertEqual(page.locator(".path-panel").count(), len(snapshot["attack_paths"]))
            self.assertEqual(page.locator(".graph-node").count(),
                             sum(len(path["entities"]) for path in snapshot["attack_paths"]))
            for panel, path in zip(page.locator(".path-panel").all(), snapshot["attack_paths"]):
                self.assertEqual(panel.locator("h3").inner_text(), path["title"])
                self.assertEqual(panel.locator("details ul li").count(), max(1, len(path["edges"])))
                for edge in path["edges"]:
                    self.assertIn(edge["label"], panel.text_content())
                for text in (path["entry_point"]["name"], path["target"]["name"], path["story"], path["remediation"]):
                    self.assertIn(text, panel.text_content())

            self.assertEqual(page.locator("#inventory-table tbody tr").count(), len(snapshot["inventory"]))
            page.locator('summary').filter(has_text="All resource-level finding records").click()
            self.assertEqual(page.locator("#findings-table tbody tr").count(), min(50, len(snapshot["findings"])))
            if len(snapshot["findings"]) > 50:
                page.locator("#findings-more").click()
                self.assertEqual(page.locator("#findings-table tbody tr").count(), min(100, len(snapshot["findings"])))
            self.assertEqual(len(self.csv_rows(self.download(page, "#findings-csv"))), len(snapshot["findings"]))

            resource = max(snapshot["inventory"], key=lambda row: row["embedded_cve_records"])
            page.locator("#detail-resource").select_option(resource["resource_id"])
            self.assertEqual(page.locator("#detail-content h3").inner_text(), resource["server_name"])
            self.assertIn(resource["resource_id"], page.locator("#detail-content").inner_text())
            findings = [finding for finding in snapshot["findings"] if finding["resource_id"] == resource["resource_id"]]
            self.assertEqual(page.locator("#detail-content ul li").count(), min(30, len(findings)))
            exported = self.csv_rows(self.download(page, '#detail-content button:first-of-type'))
            self.assertEqual([row["finding_id"] for row in exported], [row["finding_id"] for row in findings])
            cves = [cve for cve in snapshot["vulnerabilities"] if cve["resource_id"] == resource["resource_id"]]
            exported = self.csv_rows(self.download(page, '#detail-content button:last-of-type'))
            self.assertEqual([row["cve_id"] for row in exported], [row["cve_id"] for row in cves])

            for key, rows in (
                ("software", snapshot["software"]), ("vulnerabilities", snapshot["vulnerabilities"]),
                ("attack_paths", snapshot["attack_paths"]), ("controls", snapshot["posture"]["controls"]),
                ("compliance", snapshot["compliance"]["controls"]),
            ):
                with self.subTest(section=key):
                    exported = self.csv_rows(self.download(page, f'[data-export-section="{key}"]'))
                    self.assertEqual(len(exported), len(rows))
                    if key == "attack_paths":
                        self.assertEqual([json.loads(row["edges"]) for row in exported],
                                         [path["edges"] for path in rows])
                        self.assertEqual([json.loads(row["entities"]) for row in exported],
                                         [path["entities"] for path in rows])

            page.locator("#reset").click()
            page.locator("#risk").select_option("Medium")
            page.locator("#finding-status").select_option("Unhealthy")
            expected = [finding for finding in snapshot["findings"]
                        if finding["risk_level"] == "Medium" and finding["status"] == "Unhealthy"]
            self.assertEqual(page.locator("#findings-table tbody tr").count(), min(50, len(expected)))
            self.assertIn(f"of {len(expected)} matched findings", page.locator("#findings-count").inner_text())
            exported = self.csv_rows(self.download(page, "#findings-csv"))
            self.assertEqual([row["finding_id"] for row in exported], [finding["finding_id"] for finding in expected])
            groups = [group for group in snapshot["recommendation_groups"]
                      if group["risk_level"] == "Medium" and group["status"] == "Unhealthy"]
            exported = self.csv_rows(self.download(page, '[data-export-section="recommendation_groups"]'))
            self.assertEqual(len(exported), len(groups))

            page.locator("#reset").click()
            resource_type = resource.get("resource_type", "microsoft.hybridcompute/machines")
            page.locator("#resource-type").select_option(resource_type)
            expected_inventory = [row for row in snapshot["inventory"] if row.get("resource_type") == resource_type]
            exported = self.csv_rows(self.download(page, "#inventory-csv"))
            self.assertEqual([row["resource_id"] for row in exported],
                             [row["resource_id"] for row in expected_inventory])
            page.locator("#reset").click()
            page.locator('#inventory-table button[data-sort="0"]').click()
            self.assertEqual(page.locator("#inventory-table tbody tr").count(), len(snapshot["inventory"]))
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("#risk").select_option("Medium")
            page.locator("#finding-status").select_option("Unhealthy")
            self.assertEqual(len(self.csv_rows(self.download(page, "#findings-csv"))), len(expected))
            self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
            exported_json = self.download(page, "#snapshot-json")
            self.assertLessEqual(len(exported_json), 4_800_000)
            restored = tool._unpack_snapshot(json.loads(exported_json))
            self.assertEqual(restored, snapshot)
            normalized = lambda value: json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
            self.assertEqual(hashlib.sha256(normalized(restored)).hexdigest(),
                             hashlib.sha256(normalized(snapshot)).hexdigest())
            self.assertEqual(errors, [])
            self.assertEqual(external, [])
            page.close()
            context.close()

    def test_simulated_full_report_browser_filters_drilldowns_and_all_exports(self):
        self.check_report(sim._fixture(REFERENCE), sim)

    @unittest.skipUnless(CURRENT_FIXTURE.is_file(), "Private current normalized fixture is not distributed.")
    def test_current_complete_live_fixture_browser_equality_and_all_exports(self):
        self.check_report(json.loads(CURRENT_FIXTURE.read_text(encoding="utf-8")), live)

    def test_browser_plain_v1_v2_compatibility_and_explicit_malformed_rejection(self):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.set_content("<!doctype html><title>Offline decoder parity</title>")
        page.add_script_tag(content=javascript_decoder())
        snapshot = sim._fixture(REFERENCE)
        for document in (snapshot, legacy_pack(snapshot), sim._pack_snapshot(snapshot)):
            self.assertTrue(page.evaluate("document => unpackSnapshot(document)", document) == snapshot,
                            "Browser ordinary/v1/v2 snapshot mismatch.")
        literal = copy.deepcopy(snapshot)
        literal["reserved"] = [{"$missing": True}, {"$s": 0}, {"$table": [], "rows": []},
                               {"__proto__": {"polluted": True}}, [4], [0, 0], "~0", "~~0"]
        literal["float_types"] = [1.0, -0.0, 0.125, 1e30]
        packed = sim._pack_snapshot(literal)
        decoded = page.evaluate("document => JSON.stringify(unpackSnapshot(document))", packed)
        self.assertTrue(json.loads(decoded) == literal, "Browser literal/float field mismatch.")
        exported = json.loads(page.evaluate("document => JSON.stringify(document)", packed))
        restored = sim._unpack_snapshot(exported)
        self.assertEqual(restored, literal)
        self.assertTrue(all(type(value) is float for value in restored["float_types"]))
        self.assertEqual(math.copysign(1, restored["float_types"][1]), -1)
        self.assertIsNone(page.evaluate("Object.prototype.polluted"))
        outcomes = page.evaluate("""raw => JSON.parse(raw).map(document => {
          try {unpackSnapshot(document); return false;}
          catch (error) {return Boolean(error.message);}
        })""", json.dumps(malformed_documents()))
        self.assertTrue(all(outcomes))

    def test_v1_v2_browser_section_and_filtered_csv_semantics_are_identical(self):
        snapshot = sim._fixture(REFERENCE)
        context = self.browser.new_context(accept_downloads=True)
        self.addCleanup(context.close)
        exports = []
        for encoder in (legacy_pack, sim._pack_snapshot):
            page = context.new_page()
            with patch.object(sim, "_pack_snapshot", side_effect=encoder):
                document = sim._render_html(snapshot)
            page.set_content(document)
            page.locator('summary').filter(has_text="All resource-level finding records").click()
            page.locator("#provider").select_option("gcp")
            page.locator("#environment").select_option("Production")
            page.locator("#finding-status").select_option("Unhealthy")
            selectors = ["#inventory-csv", "#findings-csv"] + [
                f'[data-export-section="{key}"]' for key in
                ("software", "vulnerabilities", "attack_paths", "controls", "compliance", "recommendation_groups")
            ]
            exports.append([self.csv_rows(self.download(page, selector)) for selector in selectors])
            page.close()
        self.assertTrue(exports[0] == exports[1], "V1/v2 browser CSV contents differ.")
        self.assertEqual(len(exports[1][0]), 28)

    def test_browser_field_escaping_preserves_literal_text_without_execution_or_requests(self):
        snapshot = sim._fixture(REFERENCE)
        dangerous = '</script><img src="https://example.invalid" onerror="window.__injected=true"> & \u2028 \u2029'
        snapshot["inventory"][0]["server_name"] = dangerous
        snapshot["findings"][0]["title"] = dangerous
        snapshot["attack_paths"][0]["story"] = dangerous
        with tempfile.TemporaryDirectory() as folder, patch.object(sim.Path, "cwd", return_value=Path(folder)):
            result = sim._write_report(snapshot)
            page = self.browser.new_page()
            self.addCleanup(page.close)
            errors, external = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: external.append(request.url)
                    if request.url.startswith(("http:", "https:")) else None)
            page.goto(Path(result["report_path"]).as_uri())
            self.assertEqual(page.evaluate("snapshot.inventory[0].server_name"), dangerous)
            self.assertEqual(page.evaluate("snapshot.findings[0].title"), dangerous)
            self.assertEqual(page.evaluate("snapshot.attack_paths[0].story"), dangerous)
            self.assertIsNone(page.evaluate("window.__injected"))
            self.assertEqual(page.locator("img:not(.brand-logo)").count(), 0)
            page.locator("#detail-resource").select_option(snapshot["inventory"][0]["resource_id"])
            self.assertEqual(page.locator("#detail-content h3").text_content(), dangerous)
            self.assertEqual(errors, [])
            self.assertEqual(external, [])
            page.close()

    def test_browser_expansion_guard_precedes_allocation_and_skips_unused_sparse_defaults(self):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.set_content("<!doctype html><title>Bounded offline decoder</title>")
        page.add_script_tag(content=javascript_decoder())
        proof = page.evaluate("""raw => {
          const original = Array.from, attempts = [];
          try {
            Array.from = function(value,...args) {
              if (value && !Array.isArray(value) && typeof value === "object"
                  && Object.hasOwn(value,"length") && value.length > 0) {
                attempts.push(value.length); throw new Error("Unsafe allocation intercepted");
              }
              return original.call(this,value,...args);
            };
            const results = JSON.parse(raw).map(doc => {
              try {unpackSnapshot(doc); return "accepted";}
              catch (error) {return error.message;}
            });
            return {results,attempts};
          } finally {Array.from = original;}
        }""", json.dumps(expansion_documents()))
        self.assertEqual(proof["attempts"], [])
        self.assertTrue(all("bounded decoded expansion budget" in message for message in proof["results"]))
        result = page.evaluate("""raw => {
          const original = Array.from;
          try {
            Array.from = function(value,...args) {
              if (value && typeof value === "object" && value.length > 1000)
                throw new Error("Unused sparse default was expanded");
              return original.call(this,value,...args);
            };
            return unpackSnapshot(JSON.parse(raw));
          } finally {Array.from = original;}
        }""", json.dumps(sparse_unused_default_document()))
        self.assertEqual(result, {"rows": [{"value": None} for _ in range(100)]})
