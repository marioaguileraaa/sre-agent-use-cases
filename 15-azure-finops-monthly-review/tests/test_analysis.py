import unittest
from datetime import date, timedelta

from support import SUB_A, configure, load_tool, now


def daily_rows(start, end, per_day, extra=None):
    rows, d = [], start
    while d <= end:
        rows.append({"Cost": per_day, "UsageDate": int(d.strftime("%Y%m%d")), "ServiceName": "Storage", "PricingModel": "OnDemand", "Currency": "USD"})
        for svc, amount in (extra or {}).get(d, {}).items():
            rows.append({"Cost": amount, "UsageDate": int(d.strftime("%Y%m%d")), "ServiceName": svc, "PricingModel": "OnDemand", "Currency": "USD"})
        d += timedelta(days=1)
    return rows


def monthly(month, rg, service, cost):
    return {"Cost": cost, "BillingMonth": f"{month}-01T00:00:00", "ResourceGroupName": rg, "ServiceName": service, "Currency": "USD"}


def resource(month, rid, cost, location="EU West"):
    return {"Cost": cost, "BillingMonth": f"{month}-01T00:00:00", "ResourceId": rid, "ResourceLocation": location, "Currency": "USD"}


def rid(rg, rtype, name):
    return f"/subscriptions/{SUB_A}/resourcegroups/{rg}/providers/{rtype}/{name}"


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.config = configure(self.tool)
        self.periods = self.tool.review_periods(now())
        self.start, self.today = self.periods["daily_start"], self.periods["today"]

    def raw(self, daily=None, months=None, resources=None, **extra):
        raw = {"subs": [SUB_A], "sub_names": {SUB_A: "Prod"}, "sub_tags": {}, "rgs": {}, "budgets": [], "tags": {}, "idle": [], "advisor": [],
               "receipts": [], "skipped_subs": [], "invisible_subs": [],
               "cost": {SUB_A: {"daily": daily if daily is not None else daily_rows(self.start, self.today, 100.0),
                                "monthly": months if months is not None else [], "resources": resources if resources is not None else []}}}
        raw.update(extra)
        return raw

    def analyze(self, raw, config=None):
        return self.tool.analyze(raw, config or self.config, self.periods, now())

    def test_unusual_day_needs_the_median_the_same_weekday_and_the_floor(self):
        spike, small = date(2026, 10, 20), date(2026, 10, 27)
        extra = {spike: {"Virtual Machines": 80.0}, small: {"Bandwidth": 15.0}}
        d = self.start
        while d <= self.today:  # a weekly job every Thursday is normal: the same weekday a week before cost the same
            if d.weekday() == 3:
                extra[d] = {"Backup": 30.0}
            d += timedelta(days=1)
        a = self.analyze(self.raw(daily=daily_rows(self.start, self.today, 100.0, extra)))
        self.assertEqual([u["date"] for u in a["unusual"]], ["2026-10-20"])
        self.assertEqual(a["unusual"][0]["drivers"][0]["service"], "Virtual Machines")
        self.assertEqual(a["unusual"][0]["severity"], "high")

    def test_forecast_uses_settled_days_and_the_seven_day_run_rate(self):
        a = self.analyze(self.raw())
        self.assertEqual(a["totals"]["mtd"], 300.0)  # 1-3 Nov as recorded so far
        self.assertEqual(a["totals"]["settled_days"], 1)  # 3 Nov minus 2 days of latency
        self.assertAlmostEqual(a["totals"]["forecast"], 3000.0)
        self.assertEqual(a["totals"]["run_rate"], 100.0)

    def test_month_over_month_jump_and_new_service(self):
        months = [monthly("2026-09", "rg-app", "Virtual Machines", 1000), monthly("2026-10", "rg-app", "Virtual Machines", 1500),
                  monthly("2026-09", "rg-app", "Storage", 1000), monthly("2026-10", "rg-app", "Storage", 1100),
                  monthly("2026-10", "rg-ai", "Foundry Tools", 200)]
        a = self.analyze(self.raw(months=months))
        jumps = {(j["kind"], j["name"]): j for j in a["jumps"]}
        self.assertEqual(jumps[("service", "Virtual Machines")]["severity"], "high")
        self.assertNotIn(("service", "Storage"), jumps)
        self.assertEqual({(n["kind"], n["name"]) for n in a["new"]}, {("service", "Foundry Tools"), ("rg", "rg-ai")})
        self.assertEqual(a["totals"]["review"], 2800.0)
        self.assertEqual(a["totals"]["prev"], 2000.0)

    def test_budget_status_and_findings(self):
        def budget(name, amount, spent, forecast=None):
            props = {"amount": amount, "timeGrain": "Monthly", "currentSpend": {"amount": spent, "unit": "USD"},
                     "notifications": {"n": {"enabled": True, "threshold": 80, "thresholdType": "Actual"}}}
            if forecast is not None:
                props["forecastSpend"] = {"amount": forecast, "unit": "USD"}
            return {"name": name, "properties": props, "_scope": f"/subscriptions/{SUB_A}"}
        raw = self.raw(budgets=[budget("over", 1000, 1100, 1300), budget("fc", 1000, 500, 1200), budget("risk", 1000, 850, 880), budget("ok", 1000, 300, 600)])
        snapshot = self.tool.build_snapshot(raw, self.config, self.periods, now(), {})
        status = {b["name"]: b["status"] for b in snapshot["budgets"]}
        self.assertEqual(status, {"over": "over", "fc": "forecast_over", "risk": "risk", "ok": "ok"})
        sev = {f["title"]: f["severity"] for f in snapshot["findings"] if f["category"] == "budget"}
        self.assertEqual(sorted(sev.values()), ["critical", "high", "medium"])
        self.assertFalse([f for f in snapshot["findings"] if f["category"] == "governance"])

    def test_subscription_without_budget_gets_a_suggested_amount(self):
        snapshot = self.tool.build_snapshot(self.raw(), self.config, self.periods, now(), {})
        gov = [f for f in snapshot["findings"] if f["category"] == "governance"]
        self.assertEqual(len(gov), 1)
        self.assertIn("3,300\u00a0USD", gov[0]["action"])  # 110% of the 3,000 forecast

    def test_commitment_options_count_once(self):
        def rec(kind, term, look, amount):
            sub_cat = "Reservations" if kind == "ri" else "SavingsPlans"
            problem = "Consider virtual machine reserved instance" if kind == "ri" else "Consider purchasing a savings plan"
            return {"id": f"/x/{kind}{term}{look}", "subscriptionId": SUB_A, "problem": problem,
                    "ext": {"recommendationSubCategory": sub_cat, "term": term, "lookbackPeriod": look, "savingsAmount": str(amount),
                            "savingsCurrency": "USD", "vmSize": "Standard_D4s_v5" if kind == "ri" else "", "region": "westeurope", "scope": "Single"}}
        raw = self.raw(advisor=[rec("ri", "P1Y", "30", 150), rec("ri", "P3Y", "30", 280), rec("ri", "P1Y", "7", 140), rec("sp", "P1Y", "30", 120)])
        a = self.analyze(raw)
        self.assertEqual(a["commitment"]["best_saving"], 150.0)
        self.assertEqual(a["commitment"]["items"][0]["saving_3y"], 280.0)
        self.assertEqual(a["commitment"]["alternatives"][0]["kind"], "sp")
        self.assertEqual(a["savings_total"], 150.0)

    def test_idle_resources_use_last_month_cost_and_skip_replica_disks(self):
        disk, asr, vm, os_disk, nic = (rid("rg-a", "microsoft.compute/disks", "d1"), rid("rg-a", "microsoft.compute/disks", "vm9_osdisk-asrreplica"),
                                      rid("rg-a", "microsoft.compute/virtualmachines", "vm1"), rid("rg-a", "microsoft.compute/disks", "vm1_os"),
                                      rid("rg-a", "microsoft.network/networkinterfaces", "nic1"))
        idle = [{"id": disk, "name": "d1", "resourceGroup": "rg-a", "subscriptionId": SUB_A, "check": "unattached_disk", "size": 128, "sku": "Premium_LRS"},
                {"id": asr, "name": "vm9_osdisk-asrreplica", "resourceGroup": "rg-a", "subscriptionId": SUB_A, "check": "unattached_disk"},
                {"id": vm, "name": "vm1", "resourceGroup": "rg-a", "subscriptionId": SUB_A, "check": "deallocated_vm", "osDisk": os_disk, "dataDisks": []},
                {"id": nic, "name": "nic1", "resourceGroup": "rg-a", "subscriptionId": SUB_A, "check": "orphaned_nic"}]
        resources = [resource("2026-10", disk, 20.0), resource("2026-10", os_disk, 7.5), resource("2026-10", asr, 3.0)]
        a = self.analyze(self.raw(resources=resources, idle=idle))
        by_name = {s["name"]: s for s in a["savings"]}
        self.assertNotIn("vm9_osdisk-asrreplica", by_name)
        self.assertEqual(by_name["d1"]["saving"], 20.0)
        self.assertEqual(by_name["vm1"]["saving"], 7.5)
        self.assertEqual(by_name["nic1"]["saving"], 0.0)
        snapshot = self.tool.build_snapshot(self.raw(resources=resources, idle=idle), self.config, self.periods, now(), {})
        nic_finding = next(f for f in snapshot["findings"] if "nic1" in f["title"])
        self.assertEqual((nic_finding["severity"], nic_finding["category"]), ("info", "hygiene"))

    def test_advisor_and_resource_graph_findings_are_not_double_counted(self):
        disk = rid("rg-a", "microsoft.compute/disks", "d1")
        idle = [{"id": disk, "name": "d1", "resourceGroup": "rg-a", "subscriptionId": SUB_A, "check": "unattached_disk"}]
        advisor = [{"id": "/adv/1", "subscriptionId": SUB_A, "problem": "Review unattached disks and decide whether you still need them",
                    "resourceId": disk, "value": "d1", "ext": {}}]
        a = self.analyze(self.raw(resources=[resource("2026-10", disk, 20.0)], idle=idle, advisor=advisor))
        self.assertEqual(len([s for s in a["savings"] if s["id"] == disk]), 1)
        self.assertEqual(a["savings_total"], 20.0)
        self.assertEqual(a["savings"][0]["also"], ["advisor"])

    def test_allocation_counts_resource_group_tags_only_with_inheritance(self):
        r1, r2 = rid("rg-a", "microsoft.compute/disks", "d1"), rid("rg-b", "microsoft.compute/disks", "d2")
        raw = self.raw(resources=[resource("2026-10", r1, 60.0), resource("2026-10", r2, 40.0)],
                       tags={r1: {"CostCenter": "CC1", "Owner": "team-a", "environment": "prod"}},
                       rgs={SUB_A: {"rg-b": {"name": "rg-b", "tags": {"costcenter": "CC2", "owner": "team-b", "Environment": "dev"}}}})
        self.assertEqual(self.analyze(raw)["allocation"]["all_pct"], 100.0)
        self.tool.TAG_INHERITANCE = False
        config = configure(self.tool)
        alloc = self.analyze(raw, config)["allocation"]
        self.assertEqual(alloc["all_pct"], 60.0)
        self.assertEqual(alloc["rgs"][0]["rg"], "rg-b")

    def test_excluded_resource_groups_hide_idle_findings(self):
        self.tool.EXCLUDED_RESOURCE_GROUPS = [r"^rg-sandbox"]
        config = configure(self.tool)
        idle = [{"id": rid("rg-sandbox-1", "microsoft.compute/disks", "d1"), "name": "d1", "resourceGroup": "rg-sandbox-1", "subscriptionId": SUB_A,
                 "check": "unattached_disk"}]
        self.assertEqual(self.analyze(self.raw(idle=idle), config)["savings"], [])

    def test_mixed_currency_subscription_is_excluded_from_totals(self):
        raw = self.raw(months=[monthly("2026-10", "rg", "Storage", 100)])
        raw["subs"].append("22222222-2222-2222-2222-222222222222")
        raw["cost"]["22222222-2222-2222-2222-222222222222"] = {"daily": [dict(r, Currency="EUR") for r in daily_rows(self.start, self.today, 1.0)],
                                                              "monthly": [dict(monthly("2026-10", "rg", "Storage", 5), Currency="EUR")], "resources": []}
        a = self.analyze(raw)
        self.assertEqual(a["currency"], "USD")
        self.assertEqual(a["other_currency"], ["22222222-2222-2222-2222-222222222222"])
        self.assertEqual(a["totals"]["review"], 100.0)


if __name__ == "__main__":
    unittest.main()
