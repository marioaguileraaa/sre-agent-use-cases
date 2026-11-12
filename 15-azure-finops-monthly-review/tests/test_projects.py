"""Project dimension: which tag names the project, the allocation precedence and the project filter data (offline)."""
import csv
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from support import SUB_A, SUB_B, configure, load_tool, now

AKS = f"/subscriptions/{SUB_A}/resourcegroups/rg-k/providers/microsoft.containerservice/managedclusters/aks1"


def rid(rg, name, sub=SUB_A, rtype="microsoft.compute/disks"):
    return f"/subscriptions/{sub}/resourcegroups/{rg}/providers/{rtype}/{name}"


def cost(month, resource_id, amount, service="Storage"):
    return {"Cost": amount, "BillingMonth": f"{month}-01T00:00:00", "ResourceId": resource_id, "ServiceName": service,
            "ResourceLocation": "EU West", "Currency": "USD"}


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool("finops_projects")
        self.config = configure(self.tool, subs=(SUB_A, SUB_B))
        self.periods = self.tool.review_periods(now())
        self.review, self.prev = self.periods["review_month"], self.periods["prev_month"]

    def raw(self, resources, tags=None, rgs=None, sub_tags=None, cost_keys=(), project_rows=None):
        rg_map = {}
        for sub, rg, rg_tags, managed in rgs or []:
            rg_map.setdefault(sub, {})[rg] = {"name": rg, "tags": rg_tags, "managed_by": managed}
        cost_ = {SUB_A: {"daily": [], "monthly": [], "resources": [r for r in resources if f"/subscriptions/{SUB_A}/" in r["ResourceId"]]},
                 SUB_B: {"daily": [], "monthly": [], "resources": [r for r in resources if f"/subscriptions/{SUB_B}/" in r["ResourceId"]]}}
        if project_rows is not None:
            cost_[SUB_A]["project_tags"] = project_rows
        return {"subs": [SUB_A, SUB_B], "sub_names": {SUB_A: "Prod", SUB_B: "Shared"}, "sub_tags": sub_tags or {}, "rgs": rg_map,
                "budgets": [], "tags": tags or {}, "idle": [], "advisor": [], "receipts": [], "skipped_subs": [], "invisible_subs": [],
                "cost": cost_, "cost_tag_keys": list(cost_keys)}

    def detect(self, raw, config=None):
        return self.tool.detect_project_key(raw, config or self.config, self.periods)

    def test_tag_names_in_english_spanish_and_catalan_are_recognized(self):
        match = self.tool.project_name_match
        self.assertEqual(match("Proyecto"), (3, 3))
        self.assertEqual(match("projecte"), (3, 3))
        self.assertEqual(match("Aplicaci\u00f3n"), (2, 2))
        self.assertEqual(match("CentroCoste"), (1, 1))
        self.assertEqual(match("cost-center"), (1, 1))
        self.assertEqual(match("unidad de negocio"), (1, 1))
        self.assertEqual(match("BU"), (1, 1))
        self.assertEqual(match("ProjectName"), (2, 3))
        self.assertEqual(match("Migrate Project"), (2, 3))
        self.assertEqual(match("Solution")[0], 0)
        self.assertEqual(match("appname")[0], 0)

    def test_spanish_proyecto_tag_on_resource_groups_is_detected(self):
        r1, r2, r3 = rid("rg-tienda", "d1"), rid("rg-datos", "d2"), rid("rg-otros", "d3")
        raw = self.raw([cost(self.review, r1, 60.0), cost(self.review, r2, 30.0), cost(self.review, r3, 10.0)],
                       tags={r3: {"Departamento": "IT", "Responsable": "ana"}},
                       rgs=[(SUB_A, "rg-tienda", {"Proyecto": "Tienda online"}, ""), (SUB_A, "rg-datos", {"Proyecto": "Plataforma de datos"}, ""),
                            (SUB_A, "rg-otros", {}, "")], cost_keys=("proyecto", "departamento"))
        det = self.detect(raw)
        self.assertEqual((det["keys"], det["source"]), (["Proyecto"], "detected"))
        chosen = det["candidates"][0]
        self.assertEqual((chosen["key"], round(chosen["coverage"], 2), chosen["values"], chosen["where"]), ("Proyecto", 0.9, 2, ["rg", "cost"]))
        self.assertIn("Departamento", [c["key"] for c in det["candidates"]])
        self.assertNotIn("Responsable", [c["key"] for c in det["candidates"]])

    def test_cost_coverage_beats_a_better_name_on_one_resource(self):
        ra, rb, rc = rid("rg-a", "d1"), rid("rg-b", "d2"), rid("rg-c", "d3")
        raw = self.raw([cost(self.review, ra, 50.0), cost(self.review, rb, 45.0), cost(self.review, rc, 5.0)], tags={rc: {"project": "myapp"}},
                       rgs=[(SUB_A, "rg-a", {"CostCenter": "CC1"}, ""), (SUB_A, "rg-b", {"CostCenter": "CC2"}, ""), (SUB_A, "rg-c", {}, "")])
        self.assertEqual(self.detect(raw)["keys"], ["CostCenter"])

    def test_a_sensible_number_of_values_breaks_ties(self):
        rows = [cost(self.review, rid(f"rg-{k}", "d"), 10.0) for k in range(3)]
        rgs = [(SUB_A, f"rg-{k}", {"App": "portal", "Service": f"svc-{k}"}, "") for k in range(3)]
        self.assertEqual(self.detect(self.raw(rows, rgs=rgs))["keys"], ["Service"])

    def test_configured_or_requested_key_overrides_detection(self):
        r1 = rid("rg-a", "d1")
        raw = self.raw([cost(self.review, r1, 10.0)], rgs=[(SUB_A, "rg-a", {"project": "x", "Owner": "ana"}, "")])
        det = self.detect(raw, dict(self.config, project_keys=["Owner"], project_source="parameter"))
        self.assertEqual((det["keys"], det["source"]), (["Owner"], "parameter"))
        self.tool.PROJECT_TAG_KEYS = ["Owner"]
        self.assertEqual(configure(self.tool)["project_keys"], ["Owner"])
        self.tool.PROJECT_TAG_KEYS = "Owner"
        with self.assertRaises(self.tool.FinOpsError):
            configure(self.tool)

    def test_allocation_precedence_and_past_months(self):
        r_res, r_rg, r_mc = rid("rg-a", "d1"), rid("rg-a", "d2"), rid("mc_rg-k_aks1_westeurope", "vmss", rtype="microsoft.compute/virtualmachinescalesets")
        r_sub, r_cost, r_rule, r_none = rid("rg-s", "d4", sub=SUB_B), rid("rg-c", "d5"), rid("rg-dev-1", "d6"), rid("rg-z", "d7")
        rows = [cost(self.review, r, 10.0) for r in (r_res, r_mc, r_sub, r_cost, r_rule, r_none)] + [cost(self.prev, r_rg, 25.0)]
        raw = self.raw(rows, tags={r_res: {"Project": "Alpha"}, AKS: {"owner": "k8s"}},
                       rgs=[(SUB_A, "rg-a", {"project": "beta"}, ""), (SUB_A, "rg-k", {"PROJECT": "Kappa"}, ""),
                            (SUB_A, "mc_rg-k_aks1_westeurope", {}, AKS), (SUB_B, "rg-s", {}, ""), (SUB_A, "rg-c", {}, ""),
                            (SUB_A, "rg-dev-1", {}, ""), (SUB_A, "rg-z", {}, "")],
                       sub_tags={SUB_B: {"Project": "Sigma"}},
                       project_rows=[{"Cost": 10.0, "BillingMonth": f"{self.review}-01T00:00:00", "ResourceId": r_cost, "TagKey": "project", "TagValue": "Gamma"}])
        self.tool.PROJECT_RG_RULES = [(r"^rg-dev-", "Dev")]
        config = configure(self.tool, subs=(SUB_A, SUB_B))
        a = self.tool.analyze(raw, config, self.periods, now())
        got = {r["id"]: (r["project"], r["project_source"]) for r in a["resources"]}
        self.assertEqual(got[r_res], ("Alpha", "resource"))
        self.assertEqual(got[r_rg], ("beta", "rg"))
        self.assertEqual(got[r_mc], ("Kappa", "managed"))
        self.assertEqual(got[r_sub], ("Sigma", "sub"))
        self.assertEqual(got[r_cost], ("Gamma", "cost"))
        self.assertEqual(got[r_rule], ("Dev", "rule"))
        self.assertEqual(got[r_none], (self.tool.TEXT["proj_unallocated"], "none"))
        pj = a["projects"]
        self.assertEqual(pj["key"], "Project")
        self.assertAlmostEqual(pj["allocated_pct"], 50 / 60 * 100)
        self.assertEqual(pj["by_source"]["none"], 10.0)
        items = {it["name"]: it for it in pj["items"]}
        self.assertEqual((items["beta"]["cost"], items["beta"]["prev"]), (0.0, 25.0))  # today's tags also allocate earlier months
        self.assertTrue(pj["items"][-1]["unallocated"])

    def test_no_project_tag_raises_a_finding_and_hides_the_filter(self):
        raw = self.raw([cost(self.review, rid("rg-a", "d1"), 40.0)], rgs=[(SUB_A, "rg-a", {"Owner": "ana"}, "")])
        snapshot = self.tool.build_snapshot(raw, self.config, self.periods, now(), {})
        self.assertEqual(snapshot["projects"]["source"], "none")
        self.assertIn("No project tag found", [f["title"] for f in snapshot["findings"]])
        page = self.tool.render_html(snapshot)
        self.assertIn('id="projects"', page)
        self.assertNotIn('id="pf"', page)

    def test_parameters(self):
        p = self.tool.validate_parameters("query", "projects", 10, "E-commerce web", "Proyecto, CostCenter")
        self.assertEqual((p["project"], p["project_tag"]), ("E-commerce web", ["Proyecto", "CostCenter"]))
        for args in (("report", "summary", 15, "web", ""), ("query", "summary", 15, "", "a/b"), ("query", "summary", 15, "", "a,b,c,d,e,f"),
                     ("query", "summary", 15, "<b>", "")):
            with self.subTest(args=args):
                with self.assertRaises(self.tool.FinOpsError):
                    self.tool.validate_parameters(*args)


class ProjectFilterOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool("finops_project_outputs")
        cls.cwd = os.getcwd()
        cls.work = Path(tempfile.mkdtemp(prefix="finops-projects-"))
        os.chdir(cls.work)
        cls.result = cls.tool.main(operation="self_test")
        cls.snapshot = json.loads(Path(cls.result["snapshot_path"]).read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.cwd)
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_self_test_detects_the_project_tag_and_uses_every_level(self):
        pj = self.snapshot["projects"]
        self.assertEqual((pj["key"], pj["source"]), ("project", "detected"))
        names = {it["name"]: it for it in pj["items"]}
        self.assertEqual(names["Customer API"]["sources"].keys() >= {"managed"}, True)
        self.assertIn("resource", names["Marketing site"]["sources"])
        self.assertIn("cost", names["Load testing"]["sources"])
        self.assertIn("rule", names["Developer tools"]["sources"])
        self.assertTrue(names[self.tool.TEXT["proj_unallocated"]]["unallocated"])
        self.assertEqual(self.result["kpis"]["projects"]["tag"], "project")

    def test_html_has_the_filter_and_one_variant_per_project(self):
        page = Path(self.result["report_path"]).read_text(encoding="utf-8")
        items = self.snapshot["projects"]["items"]
        self.assertIn('<select id="pf"', page)
        for it in items:
            self.assertIn(f'<option value="{it["id"]}">', page)
            self.assertGreaterEqual(page.count(f'data-pv="{it["id"]}"'), 5)  # banner, actions, breakdown, savings strip and lists, detail
        for f in self.snapshot["findings"]:
            self.assertIn(f'data-proj="{f["project_id"]}"', page)
        self.assertIn('data-pick="p0"', page)

    def test_project_csv_and_columns(self):
        rows = list(csv.DictReader(io.StringIO(Path(self.result["projects_csv_path"]).read_text(encoding="utf-8-sig"))))
        self.assertEqual([r["project"] for r in rows], [it["name"] for it in self.snapshot["projects"]["items"]])
        self.assertAlmostEqual(sum(float(r["cost_review_month"]) for r in rows), self.snapshot["projects"]["total"], places=1)
        costs = Path(self.result["costs_csv_path"]).read_text(encoding="utf-8-sig").splitlines()[0]
        self.assertIn("project", costs.split(","))
        self.assertIn("project", Path(self.result["findings_csv_path"]).read_text(encoding="utf-8-sig").splitlines()[0].split(","))

    def test_query_filters_by_project(self):
        q = lambda view, project="": self.tool.query_view(self.snapshot, {"view": view, "limit": 50, "project": project})
        web = next(it for it in self.snapshot["projects"]["items"] if it["name"] == "E-commerce web")
        out = q("resources", "e-commerce WEB")
        self.assertEqual({r["rg"] for r in out["rows"]}, {"rg-web-prod", "rg-sql-prod"})
        self.assertEqual(out["project"]["cost"], web["cost"])
        self.assertTrue(all(s.get("project_id") == web["id"] for s in self.snapshot["savings"]["items"]
                            if s["name"] in {r["name"] for r in q("savings", "E-commerce web")["rows"]}))
        self.assertEqual(q("budgets", "E-commerce web")["project_scope"], "whole_environment")
        self.assertEqual(len(q("projects")["rows"]), len(self.snapshot["projects"]["items"]))
        with self.assertRaises(self.tool.FinOpsError) as ctx:
            q("actions", "nope")
        self.assertEqual(ctx.exception.code, "unknown_project")

    def test_project_tag_parameter_overrides_detection(self):
        result = self.tool.main(operation="self_test", project_tag="costcenter")
        self.assertEqual(result["kpis"]["projects"]["tag"], "costcenter")
        self.assertEqual(result["kpis"]["projects"]["source"], "parameter")


if __name__ == "__main__":
    unittest.main()
