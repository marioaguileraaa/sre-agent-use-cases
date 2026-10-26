"""Optional private-recorded-fixture check. Never commits/prints native rows."""

import json
import os
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from private_replay import replay_document
from support import BRANDING, TOOL


@unittest.skipUnless(os.environ.get("CASE06_PRIVATE_REPLAY_PATH"), "Opt-in private recorded preflight is not configured.")
class RecordedPrivateReplayTests(unittest.TestCase):
    def test_actual_recorded_shapes_full_fields_shared_item_ids_and_budgets(self):
        path = Path(os.environ["CASE06_PRIVATE_REPLAY_PATH"])
        data = path.read_bytes()
        original = json.loads(data.decode("utf-8-sig"))
        with patch.object(TOOL, "Identity") as identity, patch.object(TOOL, "HttpReader") as reader:
            snapshot = replay_document(original, data)
            identity.assert_not_called()
            reader.assert_not_called()
        self.assertEqual(snapshot["provenance"], "RECORDED_REPLAY")
        self.assertTrue(snapshot["replay"]["not_fresh_live_validation"])
        self.assertIsNone(snapshot["scope"]["managed_identity_client_id"])
        list_sources = [row for row in snapshot["sources"] if row["kind"] == "jobs"]
        self.assertEqual(len(snapshot["jobs"]), sum(row["records_received"] for row in list_sources))
        self.assertEqual(snapshot["summary"]["expected_protected_items"], None)
        self.assertEqual(len(snapshot["protected_items"]), sum(source["records_received"] for source in snapshot["sources"] if source["kind"] == "protected_items"))
        self.assertEqual(len({item["id"].casefold() for item in snapshot["protected_items"]}), len(snapshot["protected_items"]))
        for item in snapshot["protected_items"]:
            self.assertIsNone(item["expected_backup_jobs"])
            self.assertIsNone(item["missed_backup_jobs"])
        by_id = {source["source_id"]: source for source in snapshot["sources"]}
        for job in snapshot["jobs"]:
            raw = TOOL.native_record(by_id, job["list_ref"])
            if job["detail_ref"] is not None:
                self.assertIn("extendedInfo", TOOL.native_record(by_id, job["detail_ref"])["properties"])
            self.assertEqual(raw["properties"]["status"], job["list_status"])
        native_states = Counter(row["native_status"] for row in snapshot["jobs"])
        self.assertEqual(sum(native_states.values()), len(snapshot["jobs"]))
        if set(native_states) == {"Completed"}:
            self.assertFalse(any(row["kind"] == "job" and row["severity"] in ("Error", "Warning") for row in snapshot["human_review"]))
        artifacts = TOOL.prepare_artifacts(snapshot, BRANDING)
        self.assertEqual(json.loads(artifacts["snapshot_path"]), snapshot)
        self.assertTrue(all(len(value) <= TOOL.ARTIFACT_BYTES for value in artifacts.values()))
        decoded = artifacts["report_path"].decode("utf-8")
        self.assertIn("RECORDED REPLAY / NOT A FRESH COLLECTION", decoded)
        group_sizes = Counter(item["source_resource_id"] for item in snapshot["protected_items"])
        receipt = {
            "provenance": "RECORDED_REPLAY", "not_fresh_live_validation": True,
            "recorded_reference_utc": snapshot["reference_utc"], "fixture_sha256": snapshot["replay"]["fixture_sha256"],
            "vaults": len(snapshot["scope"]["approved_vault_ids"]), "job_records": len(snapshot["jobs"]),
            "native_states": dict(native_states), "protected_items": len(snapshot["protected_items"]),
            "shared_source_id_groups": sum(count > 1 for count in group_sizes.values()),
            "recorded_details": sum(job["detail_ref"] is not None for job in snapshot["jobs"]),
            "unrecorded_details": sum(job["detail_ref"] is None for job in snapshot["jobs"]),
            "history_unknown_vaults": snapshot["summary"]["history_unverified_vaults"],
            "artifact_bytes": {key: len(value) for key, value in artifacts.items()}, "network_calls": 0,
        }
        if os.environ.get("CASE06_PRIVATE_REPLAY_RECEIPT"):
            Path(os.environ["CASE06_PRIVATE_REPLAY_RECEIPT"]).write_text(json.dumps(receipt, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
