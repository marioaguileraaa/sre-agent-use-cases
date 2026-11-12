import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from support import TOOL, load_tool


class SelfTestOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool("finops_outputs")
        cls.cwd = os.getcwd()
        cls.work = Path(tempfile.mkdtemp(prefix="finops-test-"))
        os.chdir(cls.work)
        cls.result = cls.tool.main(operation="self_test")

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.cwd)
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_self_test_writes_five_files_without_configuration(self):
        r = self.result
        self.assertEqual((r["status"], r["provenance"], r["artifact_status"]), ("ok", "SIMULATED", "written"))
        for key in ("report_path", "snapshot_path", "findings_csv_path", "costs_csv_path", "projects_csv_path"):
            path = Path(r[key])
            self.assertTrue(path.is_file(), key)
            stem = path.name.split(".")[0]
            for suffix in ("-snapshot", "-findings", "-cost-by-resource", "-cost-by-project"):
                stem = stem.replace(suffix, "")
            self.assertTrue(self.tool.STEM_RX.fullmatch(stem))
        self.assertLessEqual(self.tool.response_bytes(r), self.tool.TRANSPORT_BYTES)
        self.assertGreater(r["kpis"]["savings_month"], 0)
        self.assertEqual(r["sharing_mode"], "local_files_only")

    def test_html_is_self_contained_and_printable(self):
        page = Path(self.result["report_path"]).read_text(encoding="utf-8")
        self.assertIn("Content-Security-Policy", page)
        self.assertIn("default-src 'none'", page)
        self.assertIn('<html lang="en">', page)
        self.assertIn("@page{size:A4", page)
        self.assertIn("SIMULATED", page)
        self.assertNotRegex(page, r"<link\b|<img[^>]+src=\"https?:|<script[^>]+src=|@import|url\(https?:")
        for href in re.findall(r'href="(https?://[^"]+)"', page):
            self.assertTrue(href.startswith(("https://portal.azure.com/", "https://learn.microsoft.com/")), href)
        for section in ("actions", "trend", "breakdown", "projects", "changes", "budgets", "savings", "allocation", "register", "coverage"):
            self.assertIn(f'id="{section}"', page)

    def test_csv_files_are_guarded_against_formula_injection(self):
        self.assertEqual(self.tool.csv_cell("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(self.tool.csv_cell("-cmd"), "'-cmd")
        rows = Path(self.result["findings_csv_path"]).read_text(encoding="utf-8-sig").splitlines()
        self.assertTrue(rows[0].startswith("severity,category,title"))
        self.assertGreater(len(rows), 5)

    def test_snapshot_round_trips_and_query_views_fit_the_transport_budget(self):
        snapshot = json.loads(Path(self.result["snapshot_path"]).read_text(encoding="utf-8"))
        self.assertEqual(snapshot["provenance"], "SIMULATED")
        self.assertEqual(len(snapshot["scope"]["subscriptions"]), 3)
        self.assertTrue(snapshot["unusual"] and snapshot["jumps"] and snapshot["new"] and snapshot["budgets"] and snapshot["no_budget"])
        for view in self.tool.VIEWS:
            out = self.tool.query_view(snapshot, {"view": view, "limit": 50})
            self.assertLessEqual(self.tool.response_bytes(out), self.tool.TRANSPORT_BYTES, view)
            self.assertTrue(out["rows"], view)

    def test_names_are_escaped_in_the_html(self):
        snapshot = json.loads(Path(self.result["snapshot_path"]).read_text(encoding="utf-8"))
        snapshot["resources"][0]["name"] = '<img src=x onerror="alert(1)">'
        page = self.tool.render_html(snapshot)
        self.assertNotIn('<img src=x onerror="alert(1)">', page)
        self.assertIn("&lt;img src=x", page)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool("finops_contract")

    def test_placeholders_return_configuration_required(self):
        result = self.tool.main()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "configuration_required")
        self.assertTrue(result["read_only"])

    def test_parameters_are_validated(self):
        self.assertEqual(self.tool.main(operation="delete")["error"]["code"], "invalid_parameter")
        self.assertEqual(self.tool.main(operation="report", view="budgets")["error"]["code"], "invalid_combination")
        self.assertEqual(self.tool.main(operation="query", limit=500)["error"]["code"], "invalid_parameter")

    def test_native_links_point_to_the_thread_files(self):
        thread = "0b6f2a3c-1d4e-4f50-8a9b-0c1d2e3f4a5b"
        root = Path(f"/root/sreagent/terminalRoot/tmp/ThreadFiles/{thread}")
        stem = "finops-review-2026-10-20261103T070000Z-0a1b2c3d"
        paths = {k: root / self.tool.OUTPUT_DIRECTORY / (stem + v) for k, v in self.tool.ARTIFACT_SUFFIXES.items()}
        links = self.tool.sharing_fields(root, paths, stem)
        self.assertEqual(links["sharing_mode"], "native_ui")
        self.assertEqual(links["report_url"], f"/api/files/tmp/ThreadFiles/{thread}/finops-review-reports/{stem}.html")

    def test_sidecar_token_claims_are_recognized(self):
        import base64
        claims = {"iss": "adc-msi-sidecar", "clientId": "abc", "scp": "https://management.azure.com/.default"}
        token = "h." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".s"
        self.assertTrue(self.tool.claim_check(token, "abc").startswith("verified"))

    def test_every_report_text_key_exists(self):
        source = TOOL.read_text(encoding="utf-8")
        keys = set(re.findall(r'\btn?\("([a-z_0-9]+)"', source))
        missing = sorted(k for k in keys if not k.endswith("_") and k not in self.tool.TEXT)
        self.assertEqual(missing, [])
        checks = ("unattached_disk", "unused_public_ip", "stopped_vm", "deallocated_vm", "empty_plan", "orphaned_nic", "old_snapshot",
                  "idle_load_balancer", "idle_nat_gateway")
        for check in checks:
            self.assertIn("chk_" + check, self.tool.TEXT)
            self.assertIn("a_idle_" + check, self.tool.TEXT)
            self.assertIn(f"'{check}'", source)
        for prefix, values in (("sev_", self.tool.SEVERITIES), ("st_", ("complete", "partial", "denied", "error", "skipped", "not_configured", "simulated")),
                               ("cat_", ("budget", "anomaly", "savings", "commitment", "allocation", "governance", "hygiene", "data")),
                               ("metric_", ("AmortizedCost", "ActualCost")), ("pm_", ("OnDemand", "Reservation", "SavingsPlan", "Spot"))):
            for value in values:
                self.assertIn(prefix + value, self.tool.TEXT)


if __name__ == "__main__":
    unittest.main()
