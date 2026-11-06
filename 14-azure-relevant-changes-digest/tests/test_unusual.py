"""Unusual-activity flags: first-time actor, DST-aware after-hours, bursts (offline)."""

import unittest
from datetime import datetime, timezone

from support import HUMAN, SUB, analyze, at, load_tool, row

KV = "microsoft.keyvault/vaults"


class UnusualTests(unittest.TestCase):
    def setUp(self):
        self.t = load_tool()

    def test_first_time_actor_flag_only_on_first_change_of_the_pair(self):
        rows = [row("microsoft.web/sites", "app1", changes={"properties.httpsOnly": ("true", "false")}, ts=at(10)),
                row("microsoft.web/sites", "app1", changes={"properties.siteConfig.alwaysOn": ("true", "false")}, ts=at(20)),
                row("microsoft.web/sites", "app2", changes={"properties.siteConfig.alwaysOn": ("true", "false")}, ts=at(30), rg="rg-other")]
        baseline = [{"changedBy": HUMAN.lower(), "subscriptionId": SUB, "rg": "rg-app", "firstSeen": at(10)}]
        analysis, *_ = analyze(self.t, rows, baseline=baseline)
        flagged = [c["resource_name"] for c in sorted(analysis["changes"], key=lambda c: c["when"]) if "first-time actor on RG" in c["flags"]]
        self.assertEqual(flagged, ["app1"])
        self.assertEqual(len(analysis["first_time"]), 1)
        self.assertEqual(analysis["first_time"][0]["changes"], 2)

    def test_after_hours_is_dst_aware_for_europe_madrid(self):
        zone, _ = self.t.business_zone("Europe/Madrid")
        summer = datetime(2026, 7, 15, 18, 30, tzinfo=timezone.utc)
        winter = datetime(2026, 1, 15, 18, 30, tzinfo=timezone.utc)
        saturday = datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)
        self.assertTrue(self.t.is_after_hours(summer, zone, (8, 20), (0, 1, 2, 3, 4)))
        self.assertFalse(self.t.is_after_hours(winter, zone, (8, 20), (0, 1, 2, 3, 4)))
        self.assertTrue(self.t.is_after_hours(saturday, zone, (8, 20), (0, 1, 2, 3, 4)))
        self.assertEqual(self.t.local_label(summer, zone), "2026-07-15 20:30 CEST")
        self.assertEqual(self.t.local_label(winter, zone), "2026-01-15 19:30 CET")

    def test_builtin_eu_rule_matches_zoneinfo_around_transitions(self):
        from zoneinfo import ZoneInfo
        fallback, real = self.t.EuropeanRuleZone(1, "CET", "CEST"), ZoneInfo("Europe/Madrid")
        for stamp in ("2026-03-29T00:59:00", "2026-03-29T01:00:00", "2026-10-25T00:59:00", "2026-10-25T01:00:00", "2026-07-01T12:00:00"):
            dt = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
            with self.subTest(stamp=stamp):
                self.assertEqual(dt.astimezone(fallback).strftime("%H:%M %Z"), dt.astimezone(real).strftime("%H:%M %Z"))

    def test_after_hours_flag_applies_to_human_changes_only(self):
        late = "2026-11-06T05:30:00Z"
        rows = [row("microsoft.web/sites", "app1", changes={"properties.httpsOnly": ("true", "false")}, ts=late),
                row("microsoft.web/sites", "app2", changes={"properties.httpsOnly": ("true", "false")}, ts=late,
                    by="9a9a9a9a-0000-4000-8000-000000000001", by_type="Application", client="Go SDK")]
        analysis, *_ = analyze(self.t, rows)
        flags = {c["resource_name"]: "after-hours" in c["flags"] for c in analysis["changes"]}
        self.assertEqual(flags, {"app1": True, "app2": False})

    def test_burst_of_ten_changes_in_fifteen_minutes(self):
        rows = [row("microsoft.web/sites", f"app{i}", changes={"properties.siteConfig.alwaysOn": ("true", "false")}, ts=at(i)) for i in range(10)]
        analysis, *_ = analyze(self.t, rows)
        self.assertEqual(len(analysis["bursts"]), 1)
        self.assertEqual(analysis["bursts"][0]["changes"], 10)
        self.assertTrue(all("burst" in c["flags"] for c in analysis["changes"]))

    def test_nine_changes_or_spread_out_changes_are_not_a_burst(self):
        nine = [row("microsoft.web/sites", f"app{i}", changes={"properties.siteConfig.alwaysOn": ("true", "false")}, ts=at(i)) for i in range(9)]
        spread = [row("microsoft.web/sites", f"s{i}", changes={"properties.siteConfig.alwaysOn": ("true", "false")}, ts=at(i * 4)) for i in range(10)]
        self.assertEqual(analyze(self.t, nine)[0]["bursts"], [])
        self.assertEqual(analyze(self.t, spread)[0]["bursts"], [])

    def test_five_deletes_in_fifteen_minutes_is_a_burst(self):
        rows = [row("microsoft.insights/scheduledqueryrules", f"alert{i}", "Delete", ts=at(i * 2)) for i in range(5)]
        analysis, *_ = analyze(self.t, rows)
        self.assertEqual(len(analysis["bursts"]), 1)
        self.assertEqual(analysis["bursts"][0]["deletes"], 5)

    def test_platform_actors_never_form_bursts(self):
        rows = [row("microsoft.compute/virtualmachines/extensions", f"vm/ext{i}", "Delete", by="System", by_type="System", ts=at(i)) for i in range(12)]
        self.assertEqual(analyze(self.t, rows)[0]["bursts"], [])


if __name__ == "__main__":
    unittest.main()
