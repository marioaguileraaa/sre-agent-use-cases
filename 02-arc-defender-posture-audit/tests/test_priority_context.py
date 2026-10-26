"""Priority ordering follows observed context, not the legacy Arc-only focus."""

import copy
import unittest

from test_arc_defender_tools import REFERENCE, sim


class ContextPriorityTests(unittest.TestCase):
    def fixture(self):
        snapshot = sim._fixture(REFERENCE)
        snapshot["provenance"] = "LIVE"
        for path in snapshot["attack_paths"]:
            path["provenance"] = "LIVE"
            path["scope"] = "Subscription context"
        for finding in snapshot["findings"]:
            if finding["category"] == "Alert":
                finding["status"] = "Resolved"
        return snapshot

    def test_native_paths_and_critical_cves_precede_arc_or_installation_gaps(self):
        snapshot = self.fixture()
        resource_id = snapshot["inventory"][0]["resource_id"]
        finding_id = next(f["finding_id"] for f in snapshot["findings"] if f["resource_id"] == resource_id)
        snapshot["vulnerabilities"].append({
            "resource_id": resource_id, "finding_id": finding_id, "cve_id": "CVE-2025-24999",
            "technical_severity": "Critical", "risk_level": "Medium",
        })
        actions = sim._review_actions(snapshot, snapshot["inventory"], snapshot["findings"])
        self.assertEqual([a["action_id"] for a in actions[:2]], ["review-attack-paths", "review-critical-cves"])
        self.assertGreater(actions[0]["affected_paths"], 0)
        self.assertEqual(actions[0]["source_recommended_breaks"], sorted({
            p["remediation"] for p in snapshot["attack_paths"]
        }))
        self.assertEqual(actions[1]["cve_occurrences"], 1)
        self.assertIn("do not relabel native", actions[1]["reason"])
        self.assertEqual(snapshot["vulnerabilities"][-1]["risk_level"], "Medium")

    def test_true_active_alert_investigation_stays_first(self):
        snapshot = sim._fixture(REFERENCE)
        actions = sim._review_actions(snapshot, snapshot["inventory"], snapshot["findings"])
        self.assertEqual(actions[0]["action_id"], "investigate-alerts")
        self.assertEqual(actions[1]["action_id"], "review-demo-chains")
        self.assertIn("SIMULATED", actions[1]["title"])

    def test_absent_or_medium_risk_paths_do_not_create_a_high_risk_action(self):
        snapshot = self.fixture()
        for path in snapshot["attack_paths"]:
            path["risk_level"] = "Medium"
        actions = sim._review_actions(snapshot, snapshot["inventory"], snapshot["findings"])
        self.assertNotIn("review-attack-paths", {a["action_id"] for a in actions})

    def test_filtered_actions_do_not_use_unrelated_subscription_paths(self):
        snapshot = self.fixture()
        unrelated = [
            r for r in snapshot["inventory"]
            if all(r["resource_id"] not in p["resource_ids"] for p in snapshot["attack_paths"])
        ]
        findings = [f for f in snapshot["findings"] if f["resource_id"] in {r["resource_id"] for r in unrelated}]
        actions = sim._review_actions(snapshot, unrelated, findings)
        self.assertNotIn("review-attack-paths", {a["action_id"] for a in actions})


if __name__ == "__main__":
    unittest.main()
