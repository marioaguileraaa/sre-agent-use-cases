"""OFFLINE tests only: all tenant/vault/job responses are SIMULATED."""

import base64
import copy
import csv
import hashlib
import inspect
import io
import json
import os
import re
import tempfile
import types
import unittest
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path, PurePosixPath
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import urlencode

from support import (
    BRANDING, CASE, CLIENT, HOSTILE_TEXT, ITEM_A, ITEM_B, PRECISE_INTEGER, REFERENCE,
    SUBSCRIPTION, TENANT, TOOL, VAULT_A, VAULT_B, FakeReader, config, job, simulated_snapshot,
)


@contextmanager
def temporary_cwd():
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="case06-unit-") as directory:
        try:
            os.chdir(directory)
            yield Path(directory)
        finally:
            os.chdir(previous)


def parsed_csv(value):
    return list(csv.DictReader(io.StringIO(value.decode("utf-8-sig"), newline="")))


def source(snapshot, kind, vault=VAULT_A):
    return next(row for row in snapshot["sources"] if row["kind"] == kind and row["scope_id"] == vault)


class ContractTests(unittest.TestCase):
    def test_schema_signature_defaults_and_rejected_month(self):
        schema = json.loads((CASE / "tool-parameters.schema.json").read_text(encoding="utf-8"))
        signature = inspect.signature(TOOL.main)
        self.assertEqual(set(schema["properties"]), set(signature.parameters))
        self.assertFalse(schema["additionalProperties"])
        for name, parameter in signature.parameters.items():
            self.assertEqual(parameter.default, schema["properties"][name]["default"])
            self.assertIs(parameter.annotation, str)
        self.assertEqual(schema["properties"]["period"]["enum"], ["last_14d", "last_24h"])
        for invalid in ("previous_month", "last_30d", "", None, 14, True, "last_14d\n"):
            with self.subTest(invalid=invalid), patch.object(TOOL, "Identity") as identity:
                result = TOOL.main(invalid)
                self.assertEqual(result["error"]["code"], "invalid_parameter")
                identity.assert_not_called()

    def test_generic_configuration_fails_before_authentication_or_files(self):
        with temporary_cwd() as cwd, patch.object(TOOL, "Identity") as identity:
            result = TOOL.main()
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error"]["code"], "configuration_required")
            self.assertFalse(result["artifacts_created"])
            self.assertEqual(list(cwd.iterdir()), [])
            identity.assert_not_called()

    def test_explicit_fixed_configuration_full_id_and_history(self):
        history = {VAULT_A: {"from_utc": "2026-09-30T09:00:00Z", "through_utc": "2026-10-14T09:00:00Z",
                             "evidence": "SIMULATED verified interval receipt"}}
        with patch.multiple(TOOL, SUBSCRIPTION_ID=SUBSCRIPTION, TENANT_ID=TENANT,
                            MANAGED_IDENTITY_CLIENT_ID=CLIENT, APPROVED_VAULT_IDS=[VAULT_A, VAULT_B], VERIFIED_HISTORY=history):
            result = TOOL.validate_config()
            self.assertEqual(result["vault_ids"], [VAULT_A, VAULT_B])
            self.assertIn(VAULT_A.casefold(), result["history"])
            for bad in ([VAULT_A, VAULT_A.upper()], [], ["https://invalid.example/vault"], [VAULT_A.replace(SUBSCRIPTION, TENANT)]):
                with self.subTest(bad=bad), patch.object(TOOL, "APPROVED_VAULT_IDS", bad):
                    with self.assertRaises(TOOL.EvidenceError):
                        TOOL.validate_config()
            with patch.object(TOOL, "VERIFIED_HISTORY", {VAULT_A: {"from_utc": "bad"}}):
                with self.assertRaises(TOOL.EvidenceError):
                    TOOL.validate_config()

    def test_window_utc_boundaries_and_missing_dates(self):
        window = TOOL.requested_window("last_14d", REFERENCE)
        self.assertEqual(window["start_utc"], "2026-09-30T09:00:00Z")
        cases = {"2026-09-30T09:00:00Z": "in_requested_window", "2026-10-14T08:59:59.9999999Z": "in_requested_window",
                 "2026-09-30T08:59:59Z": "outside_requested_window", "2026-10-14T09:00:00Z": "outside_requested_window",
                 "2026-10-14T11:00:00+02:00": "outside_requested_window", "2026-10-14T10:59:59+02:00": "in_requested_window",
                 "2026-10-14T08:00:00": "unknown", None: "unknown", "bad": "unknown"}
        for value, expected in cases.items():
            self.assertEqual(TOOL.temporal_membership(value, window), expected)
        short = TOOL.requested_window("last_24h", REFERENCE)
        self.assertEqual(short["start_utc"], "2026-10-13T09:00:00Z")
        self.assertTrue(short["cadence_is_not_coverage"])
        self.assertIsNone(TOOL.duration_seconds("not-duration"))
        self.assertIsNone(TOOL.duration_seconds("P"))
        self.assertEqual(TOOL.duration_seconds("P1DT2H3M4.25S"), 93784.25)

    def test_jobs_api_filter_is_12_hour_utc_not_iso_or_locale_dependent(self):
        self.assertEqual(TOOL.backup_filter_time(REFERENCE), "2026-10-14 09:00:00 AM")
        self.assertEqual(TOOL.backup_filter_time(REFERENCE.replace(hour=0)), "2026-10-14 12:00:00 AM")
        self.assertEqual(TOOL.backup_filter_time(REFERENCE.replace(hour=12)), "2026-10-14 12:00:00 PM")
        self.assertEqual(TOOL.backup_filter_time(REFERENCE.replace(hour=23)), "2026-10-14 11:00:00 PM")
        snapshot, reader = simulated_snapshot()
        from urllib.parse import parse_qsl, urlsplit
        url = next(url for url, source_id in reader.calls if source_id == "vault:0:jobs")
        query = dict(parse_qsl(urlsplit(url).query))
        self.assertEqual(query["$filter"], "startTime eq '2026-09-30 09:00:00 AM' and endTime eq '2026-10-14 09:00:00 AM'")
        self.assertEqual(snapshot["requested_window"]["start_utc"], "2026-09-30T09:00:00Z")


class EvidenceTests(unittest.TestCase):
    def test_all_states_operations_original_properties_and_utc(self):
        snapshot, reader = simulated_snapshot()
        self.assertEqual(snapshot["provenance"], "SIMULATED")
        self.assertEqual(len(snapshot["jobs"]), 20)
        by_name = {row["name"]: row for row in snapshot["jobs"]}
        for index, expected in enumerate(("failed", "warning", "warning", "in_progress", "completed", "cancelled",
                                          "unknown", "warning", "cancelled", "warning")):
            self.assertEqual(by_name["synthetic-" + str(index)]["state_category"], expected)
        self.assertEqual(by_name["synthetic-transition"]["list_status"], "Failed")
        self.assertEqual(by_name["synthetic-transition"]["detail_status"], "Completed")
        self.assertTrue(by_name["synthetic-transition"]["state_changed"])
        self.assertEqual(by_name["synthetic-restore"]["operation_group"], "restore")
        self.assertEqual(by_name["synthetic-delete"]["operation_group"], "delete")
        self.assertEqual(by_name["synthetic-configure"]["operation_group"], "other")
        self.assertEqual(snapshot["summary"]["backup_job_records_in_window"], 14)
        self.assertEqual(snapshot["summary"]["other_operation_records_in_window"], 3)
        self.assertEqual(snapshot["summary"]["unknown_time_records"], 1)
        self.assertEqual(snapshot["summary"]["outside_window_records"], 2)
        self.assertEqual(snapshot["reference_utc"], "2026-10-14T09:00:00Z")
        self.assertEqual(snapshot["collection_finished_utc"], "2026-10-14T09:00:20Z")
        raw = TOOL.native_record({row["source_id"]: row for row in snapshot["sources"]}, by_name["synthetic-0"]["detail_ref"])
        self.assertEqual(raw["properties"]["syntheticPreciseInteger"], PRECISE_INTEGER)
        self.assertEqual(raw["properties"]["extendedInfo"]["propertyBag"]["Unmodeled property"], HOSTILE_TEXT)
        self.assertEqual(raw["properties"]["duration"], "PT2M3.25S")
        self.assertEqual(source(snapshot, "jobs")["responses"][0]["body"]["unmodeledEnvelope"]["integer"], PRECISE_INTEGER)
        self.assertEqual(len(source(snapshot, "jobs")["responses"]), 2)
        self.assertGreater(len(reader.calls), 20)
        self.assertTrue(all("/backupJobs" in url or "/backupProtectedItems" in url or "api-version=" in url for url, _ in reader.calls))

    def test_failed_list_transition_and_completed_with_issue_text_remain_reviewable(self):
        snapshot, _ = simulated_snapshot()
        review = {row.get("record_key"): row for row in snapshot["human_review"] if row["kind"] == "job"}
        jobs = {row["name"]: row for row in snapshot["jobs"]}
        self.assertEqual(review[jobs["synthetic-transition"]["record_key"]]["severity"], "Error")
        complete = jobs["synthetic-complete-with-evidence"]
        self.assertEqual(complete["native_status"], "Completed")
        self.assertTrue(complete["native_issue_evidence_paths"])
        self.assertEqual(review[complete["record_key"]]["severity"], "Attention")
        self.assertTrue(all(row["incident_status"] == "not_created" for row in snapshot["human_review"]))

    def test_observed_items_not_intent_and_no_friendly_name_join(self):
        snapshot, _ = simulated_snapshot()
        jobs = {row["name"]: row for row in snapshot["jobs"]}
        items = {row["id"]: row for row in snapshot["protected_items"]}
        self.assertEqual(jobs["synthetic-0"]["matched_item_id"], ITEM_A)
        self.assertEqual(jobs["synthetic-0"]["native_item_id_candidates"], [ITEM_A.upper()])
        self.assertEqual(items[ITEM_A]["matched_backup_job_records"], 1)
        self.assertEqual(items[ITEM_B]["matched_backup_job_records"], 0)
        self.assertIsNone(jobs["synthetic-4"]["matched_item_id"])
        self.assertEqual(jobs["synthetic-4"]["association_status"], "source_resource_id_is_not_item_identity")
        self.assertEqual(len(jobs["synthetic-4"]["source_resource_matches"]), 2)
        self.assertEqual(jobs["synthetic-ambiguous-id"]["association_status"], "source_resource_id_is_not_item_identity")
        self.assertGreaterEqual(len(jobs["synthetic-ambiguous-id"]["source_resource_matches"]), 2)
        self.assertIsNone(jobs["synthetic-ambiguous-id"]["matched_item_id"])
        self.assertEqual(len({item["vault_id"] for item in snapshot["protected_items"]}), 2)
        self.assertEqual(len({item["vault_name"] for item in snapshot["protected_items"]}), 1)
        for item in snapshot["protected_items"]:
            self.assertIsNone(item["expected_backup_jobs"])
            self.assertIsNone(item["missed_backup_jobs"])
            self.assertFalse(item["policy_schedule_evaluated"])
        self.assertIsNone(snapshot["summary"]["expected_protected_items"])
        self.assertIsNone(snapshot["summary"]["protection_coverage_percentage"])

    def test_history_gap_is_not_job_span_or_invented_rest_retention(self):
        snapshot, _ = simulated_snapshot()
        ledger = snapshot["history_coverage"][0]
        self.assertEqual(ledger["history_status"], "unknown")
        self.assertEqual(ledger["unverified_or_unknown_intervals"][0]["start_utc"], snapshot["requested_window"]["start_utc"])
        self.assertIsNone(ledger["rest_retention_days"])
        window = snapshot["requested_window"]
        verified = {VAULT_A.casefold(): {"from_utc": "2026-10-01T00:00:00Z", "through_utc": "2026-10-13T00:00:00Z",
                                        "evidence": "SIMULATED actual interval, not min/max"}}
        result = TOOL.history_coverage(VAULT_A, window, verified, snapshot["jobs"], source(snapshot, "jobs"))
        self.assertEqual(result["history_status"], "partial_verified_interval")
        self.assertEqual(len(result["unverified_or_unknown_intervals"]), 2)
        self.assertEqual(result["verified_available_intervals"][0]["start_utc"], "2026-10-01T00:00:00Z")
        complete = TOOL.history_coverage(VAULT_A, window, config(True)["history"], snapshot["jobs"], source(snapshot, "jobs"))
        self.assertEqual(complete["history_status"], "verified_interval")
        self.assertEqual(complete["unverified_or_unknown_intervals"], [])
        outside = {VAULT_A.casefold(): {"from_utc": "2020-01-01T00:00:00Z", "through_utc": "2020-02-01T00:00:00Z", "evidence": "SIMULATED old interval"}}
        self.assertEqual(TOOL.history_coverage(VAULT_A, window, outside, [], source(snapshot, "jobs"))["history_status"], "unknown")

    def test_valid_empty_sources_are_not_successful_backups(self):
        reader = FakeReader()
        reader.jobs_a, reader.items_a, reader.items_b = [], [], []
        reader.overrides.update({"vault:0:jobs": {"value": []}, "vault:0:items": {"value": []}})
        snapshot, _ = simulated_snapshot(reader)
        self.assertEqual(snapshot["jobs"], [])
        self.assertEqual(snapshot["protected_items"], [])
        self.assertEqual(snapshot["summary"]["backup_job_records_in_window"], 0)
        self.assertIsNone(snapshot["summary"]["expected_protected_items"])
        self.assertEqual(source(snapshot, "jobs")["status"], "complete")
        self.assertTrue(source(snapshot, "jobs")["pagination_complete"])
        self.assertEqual(snapshot["assessment_status"], "partial")
        self.assertIn("No observed jobs is not proof that all backups succeeded.", snapshot["business_limits"])

    def test_denied_vault_does_not_hide_other_vaults_or_make_healthy_zero(self):
        reader = FakeReader()
        for kind in ("inventory", "items", "jobs"):
            source_id = "vault:1:" + kind
            reader.overrides[source_id] = TOOL.EvidenceError("access_denied", "Read returned HTTP 403.", source_id, 403)
        snapshot, _ = simulated_snapshot(reader)
        self.assertEqual(len(snapshot["jobs"]), 20)
        self.assertEqual(source(snapshot, "jobs", VAULT_B)["status"], "denied")
        self.assertFalse(source(snapshot, "jobs", VAULT_B)["pagination_complete"])
        self.assertEqual(source(snapshot, "jobs", VAULT_B)["records_received"], 0)
        self.assertEqual(snapshot["scope"]["approved_vault_ids"], [VAULT_A, VAULT_B])
        self.assertGreater(snapshot["summary"]["source_issues"], 2)

    def test_partial_second_page_preserves_every_first_page_row_and_metadata(self):
        reader = FakeReader()
        def page_or_denied(url):
            if "$skipToken=" in url or "%24skipToken=" in url:
                return TOOL.EvidenceError("access_denied", "Read returned HTTP 403.", "vault:0:jobs", 403)
            return {"value": copy.deepcopy(reader.jobs_a[:7]), "nextLink": url + "&%24skipToken=SIMULATED", "allEnvelopeFields": {"keep": HOSTILE_TEXT}}
        reader.overrides["vault:0:jobs"] = page_or_denied
        snapshot, _ = simulated_snapshot(reader)
        ledger = source(snapshot, "jobs")
        self.assertEqual(ledger["status"], "partial")
        self.assertEqual(ledger["records_received"], 7)
        self.assertEqual(len(snapshot["jobs"]), 7)
        self.assertEqual(ledger["responses"][0]["body"]["allEnvelopeFields"]["keep"], HOSTILE_TEXT)
        self.assertFalse(ledger["pagination_complete"])
        self.assertEqual(ledger["errors"][-1]["http_status"], 403)

    def test_detail_failures_and_identity_mismatch_preserve_list_and_raw_details(self):
        reader = FakeReader()
        reader.overrides["vault:0:detail:1"] = TOOL.EvidenceError("access_denied", "Read returned HTTP 403.", "vault:0:detail:1", 403)
        wrong = copy.deepcopy(reader.jobs_a[1])
        wrong["id"] = VAULT_B + "/backupJobs/wrong-job"
        wrong["properties"]["status"] = "Completed"
        reader.overrides["vault:0:detail:2"] = wrong
        snapshot, _ = simulated_snapshot(reader)
        self.assertEqual(len(snapshot["jobs"]), 20)
        self.assertEqual(snapshot["jobs"][0]["native_status"], "Failed")
        self.assertIsNone(snapshot["jobs"][0]["detail_ref"])
        self.assertEqual(snapshot["jobs"][0]["details_collection_status"], "denied")
        self.assertEqual(snapshot["jobs"][1]["native_status"], "CompletedWithWarnings")
        mismatch = next(row for row in snapshot["sources"] if row["source_id"] == "vault:0:detail:2")
        self.assertEqual(mismatch["responses"][0]["body"], wrong)
        self.assertEqual(mismatch["status"], "partial")
        self.assertIsNone(snapshot["jobs"][1]["detail_ref"])

    def test_page_and_detail_bounds_are_explicit_and_lossless_for_received_data(self):
        with patch.object(TOOL, "MAX_PAGES", 1), patch.object(TOOL, "MAX_DETAIL_READS", 2):
            snapshot, _ = simulated_snapshot()
        self.assertEqual(len(snapshot["jobs"]), 7)
        self.assertEqual(source(snapshot, "jobs")["status"], "partial")
        self.assertEqual(len(source(snapshot, "jobs")["responses"]), 1)
        cap = source(snapshot, "job_details_bound")
        self.assertEqual(len(cap["pending_job_ids"]), 5)
        self.assertEqual(cap["status"], "not_collected")
        self.assertEqual(snapshot["jobs"][2]["details_collection_status"], "not_collected")
        self.assertEqual(snapshot["jobs"][2]["native_status"], "Warning")
        with patch.object(TOOL, "MAX_ROWS", 2):
            snapshot, _ = simulated_snapshot()
        self.assertEqual(len(snapshot["jobs"]), 7)
        self.assertEqual(source(snapshot, "jobs")["errors"][-1]["code"], "row_bound")

    def test_malformed_rows_and_duplicate_ids_are_retained_not_silently_dropped(self):
        reader = FakeReader()
        duplicate = copy.deepcopy(reader.jobs_a[0])
        reader.overrides["vault:0:jobs"] = {"value": [duplicate, copy.deepcopy(duplicate), {"properties": {}}, "invalid-native-row"]}
        snapshot, _ = simulated_snapshot(reader)
        self.assertEqual(len(snapshot["jobs"]), 4)
        self.assertEqual(len({row["record_key"] for row in snapshot["jobs"]}), 4)
        ledger = source(snapshot, "jobs")
        self.assertEqual(ledger["records_received"], 4)
        self.assertEqual(ledger["responses"][0]["body"]["value"][-1], "invalid-native-row")
        self.assertTrue(any(row["code"] == "duplicate_identity" for row in ledger["errors"]))
        self.assertEqual(snapshot["jobs"][-1]["state_category"], "unknown")
        self.assertEqual(ledger["status"], "partial")
        self.assertEqual(sum("/backupJobs/synthetic-0?" in url for url, _ in reader.calls), 1)

    def test_invalid_subscription_stops_instead_of_switching_identity(self):
        reader = FakeReader()
        reader.overrides["subscription"] = {"subscriptionId": SUBSCRIPTION, "tenantId": CLIENT, "state": "Enabled"}
        with self.assertRaises(TOOL.EvidenceError) as caught:
            simulated_snapshot(reader)
        self.assertEqual(caught.exception.code, "subscription_mismatch")
        self.assertEqual(len(reader.calls), 1)


class PaginationAndHttpTests(unittest.TestCase):
    def setUp(self):
        self.initial = TOOL.ARM_ORIGIN + VAULT_A + "/backupJobs?" + urlencode({
            "api-version": TOOL.BACKUP_API_VERSION, "$filter": "startTime eq '2026-09-30 09:00:00 AM' and endTime eq '2026-10-14 09:00:00 AM'",
        })

    def test_native_continuation_only_preserves_exact_scope_filter_and_version(self):
        valid = self.initial + "&%24skipToken=" + "%3CSIMULATED%3E"
        self.assertEqual(TOOL.next_link(valid, self.initial), valid)
        bad = [
            valid.replace("management.azure.com", "evil.example"),
            valid.replace("https://", "http://"),
            valid.replace(VAULT_A, VAULT_B),
            valid.replace("/backupJobs?", "/backupProtectedItems?"),
            valid.replace(TOOL.BACKUP_API_VERSION, "2017-07-01"),
            valid + "&api-version=" + TOOL.BACKUP_API_VERSION,
            valid + "&%24skiptoken=second", valid + "&skipToken=second",
            valid + "&%24top=1", valid + "&scope=all", valid + "#fragment",
            valid.replace("management.azure.com", "user@management.azure.com"),
            valid.replace("management.azure.com", "management.azure.com:444"),
            valid.replace("/backupJobs?", "/../backupJobs?"),
            valid.replace("/backupJobs?", "/%2e%2e/backupJobs?"),
            valid.replace("/backupJobs?", "/%255cbackupJobs?"), valid + "\r\n",
            self.initial, self.initial + "&%24skipToken=", "/relative?skipToken=bad",
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(TOOL.EvidenceError):
                TOOL.next_link(value, self.initial)

    def test_failed_or_missing_continuation_keeps_received_pages(self):
        for tail in ({"nextLink": "https://evil.example/"}, {"nextLink": ""}, {"totalCount": 50}, {"truncated": True}):
            reader = FakeReader()
            reader.overrides["vault:0:jobs"] = {"value": [reader.jobs_a[0]], **tail}
            snapshot, _ = simulated_snapshot(reader)
            self.assertEqual(len(snapshot["jobs"]), 1)
            self.assertEqual(source(snapshot, "jobs")["status"], "partial")
            self.assertFalse(source(snapshot, "jobs")["pagination_complete"])
            self.assertEqual(len(source(snapshot, "jobs")["responses"]), 1)

    def test_looped_continuation_is_not_complete(self):
        reader = FakeReader()
        def repeated(url):
            initial = url.split("&%24skipToken=")[0]
            return {"value": [], "nextLink": initial + "&%24skipToken=same"}
        reader.overrides["vault:0:jobs"] = repeated
        snapshot, _ = simulated_snapshot(reader)
        self.assertEqual(source(snapshot, "jobs")["status"], "partial")
        self.assertEqual(source(snapshot, "jobs")["errors"][-1]["code"], "pagination_loop")

    def test_nonarray_is_not_valid_empty(self):
        reader = FakeReader()
        reader.overrides["vault:0:jobs"] = {"unexpected": [], "keep": "SIMULATED malformed source"}
        snapshot, _ = simulated_snapshot(reader)
        self.assertEqual(source(snapshot, "jobs")["status"], "partial")
        self.assertEqual(source(snapshot, "jobs")["responses"][0]["body"]["keep"], "SIMULATED malformed source")
        self.assertFalse(source(snapshot, "jobs")["pagination_complete"])

    def test_http_reader_allows_only_enumerated_get_contracts(self):
        reader = TOOL.HttpReader(Mock(), config())
        reader.allow(self.initial)
        reader.allow(TOOL.ARM_ORIGIN + VAULT_A + "?api-version=" + TOOL.VAULT_API_VERSION)
        reader.allow(TOOL.ARM_ORIGIN + VAULT_A + "/backupJobs/synthetic?api-version=" + TOOL.BACKUP_API_VERSION)
        for value in (
            self.initial.replace(VAULT_A, VAULT_A.replace(SUBSCRIPTION, TENANT)), self.initial.replace("https://", "http://"),
            self.initial.replace("management.azure.com", "evil.example"),
            TOOL.ARM_ORIGIN + VAULT_A + "/backupJobs/synthetic/cancel?api-version=" + TOOL.BACKUP_API_VERSION,
            TOOL.ARM_ORIGIN + VAULT_A + "/backupPolicies?api-version=" + TOOL.BACKUP_API_VERSION,
            TOOL.ARM_ORIGIN + VAULT_A + "?api-version=" + TOOL.VAULT_API_VERSION + "&extra=all",
        ):
            with self.subTest(value=value), self.assertRaises(TOOL.EvidenceError):
                reader.allow(value)
        reader.opener = Mock()
        reader.identity.token.return_value = "SIMULATED-NEVER-A-REAL-TOKEN"
        reader.opener.open.side_effect = HTTPError(self.initial, 403, "private error body", {}, io.BytesIO(b"secretValue"))
        with self.assertRaises(TOOL.EvidenceError) as caught:
            reader.request(self.initial, "synthetic-http")
        self.assertEqual(caught.exception.http_status, 403)
        self.assertNotIn("secretValue", json.dumps(caught.exception.public()))
        self.assertEqual(reader.opener.open.call_args.args[0].method, "GET")
        self.assertEqual(reader.opener.open.call_count, 1)

    def test_http_bounds_and_no_redirect(self):
        reader = TOOL.HttpReader(Mock(), config())
        reader.allow(self.initial)
        reader.opener = Mock()
        reader.attempts = TOOL.MAX_HTTP_ATTEMPTS
        with self.assertRaises(TOOL.EvidenceError) as caught:
            reader.request(self.initial, "synthetic-http")
        self.assertEqual(caught.exception.code, "collection_bound")
        reader.opener.open.assert_not_called()
        self.assertIsNone(TOOL.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example/"))

    def test_managed_identity_is_explicit_and_claims_must_match(self):
        identity_module, errors_module = types.ModuleType("azure.identity"), types.ModuleType("azure.core.exceptions")
        error = type("SyntheticIdentityError", (Exception,), {})
        identity_module.CredentialUnavailableError = error
        errors_module.ClientAuthenticationError = error
        errors_module.ServiceRequestError = error
        credential = Mock()
        identity_module.ManagedIdentityCredential = Mock(return_value=credential)
        def encoded_token(client):
            claims = {"tid": TENANT, "appid": client, "aud": TOOL.ARM_ORIGIN + "/"}
            encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
            return "header." + encoded + ".SIMULATED-not-signed"
        with patch.dict("sys.modules", {"azure.identity": identity_module, "azure.core.exceptions": errors_module}):
            credential.get_token.return_value = types.SimpleNamespace(token=encoded_token(CLIENT))
            identity = TOOL.Identity(config())
            self.assertEqual(identity.token(), encoded_token(CLIENT))
            identity_module.ManagedIdentityCredential.assert_called_once_with(client_id=CLIENT)
            credential.get_token.assert_called_once_with(TOOL.ARM_ORIGIN + "/.default")
            credential.get_token.return_value = types.SimpleNamespace(token=encoded_token(TENANT))
            with self.assertRaises(TOOL.EvidenceError) as caught:
                identity.token()
            self.assertEqual(caught.exception.code, "identity_mismatch")
            identity.close()
            credential.close.assert_called_once()


class ExportAndStorageTests(unittest.TestCase):
    def test_real_four_file_write_exact_json_embedded_bytes_and_csv_all_rows_fields(self):
        snapshot, _ = simulated_snapshot()
        expected_json = TOOL.json_bytes(snapshot)
        jobs_csv, coverage_csv = TOOL.export_csvs(snapshot)
        with temporary_cwd() as cwd:
            result = TOOL.write_report(snapshot, BRANDING)
            self.assertEqual(result["artifact_status"], "written")
            self.assertEqual(result["sharing_mode"], "local_files_only")
            self.assertFalse(result["http_verified"])
            self.assertLessEqual(len(json.dumps(result).encode("utf-8")), 3500)
            self.assertEqual(len(list((cwd / "azure-backup-reports").iterdir())), 4)
            document = Path(result["snapshot_path"]).read_bytes()
            self.assertEqual(document, expected_json)
            self.assertEqual(json.loads(document), snapshot)
            self.assertEqual(hashlib.sha256(document).hexdigest(), result["snapshot_sha256"])
            rendered = Path(result["report_path"]).read_text(encoding="utf-8")
            embedded = re.search(r'<script id="snapshot-bytes" type="application/octet-stream">([^<]+)</script>', rendered)[1]
            self.assertEqual(base64.b64decode(embedded), document)
            self.assertNotIn(HOSTILE_TEXT, rendered)
            self.assertNotIn('<img src="https://invalid.example/', rendered)
            self.assertEqual(Path(result["jobs_csv_path"]).read_bytes(), jobs_csv)
            self.assertEqual(Path(result["coverage_csv_path"]).read_bytes(), coverage_csv)
            for key in ("jobs", "coverage"):
                embedded_csv = re.search(r'<script id="' + key + r'-csv-bytes" type="application/octet-stream">([^<]+)</script>', rendered)[1]
                self.assertEqual(base64.b64decode(embedded_csv), jobs_csv if key == "jobs" else coverage_csv)
            self.assertTrue(all(size <= 4_800_000 for size in result["artifact_bytes"].values()))
        jobs = parsed_csv(jobs_csv)
        self.assertEqual(len(jobs), len(snapshot["jobs"]))
        self.assertTrue(set(snapshot["jobs"][0]) <= set(jobs[0]))
        self.assertEqual(json.loads(jobs[0]["native_list_json"])["properties"]["syntheticPreciseInteger"], PRECISE_INTEGER)
        self.assertEqual(json.loads(jobs[0]["native_detail_json"])["properties"]["errorDetails"][0]["errorCode"], 42)
        coverage = parsed_csv(coverage_csv)
        self.assertEqual(len(coverage), len(snapshot["protected_items"]) + len(snapshot["sources"]) + len(snapshot["history_coverage"]))
        item_rows = [row for row in coverage if row["record_type"] == "protected_item"]
        self.assertTrue(set(snapshot["protected_items"][0]) <= set(item_rows[0]))
        self.assertEqual(json.loads(item_rows[0]["native_source_json"])["properties"]["syntheticPreciseInteger"], PRECISE_INTEGER)
        source_rows = [json.loads(row["full_record_json"]) for row in coverage if row["record_type"] == "source_ledger"]
        self.assertEqual(source_rows, snapshot["sources"])

    def test_csv_formula_safe_text_preserves_original_json(self):
        cases = ("=1+1", "+command", "-123", "@SUM(A1)", "\t=1+1", "\r\n@evil", "  =1+1", "\ufeff=1+1", "\x00@evil")
        for value in cases:
            self.assertEqual(TOOL.csv_cell(value), "'" + value)
        self.assertEqual(TOOL.csv_cell(0), "0")
        self.assertEqual(TOOL.csv_cell(None), "")
        text = 'safe, "quoted"\nnext line'
        self.assertEqual(parsed_csv(TOOL.csv_bytes([{"value": text}], ["value"]))[0]["value"], text)
        snapshot, _ = simulated_snapshot()
        snapshot["jobs"][0]["entity_name"] = "=SIMULATED"
        self.assertEqual(parsed_csv(TOOL.export_csvs(snapshot)[0])[0]["entity_name"], "'=SIMULATED")
        self.assertEqual(json.loads(TOOL.json_bytes(snapshot))["jobs"][0]["entity_name"], "=SIMULATED")

    def test_actual_html_overflow_and_json_overflow_fail_before_any_writes(self):
        snapshot, _ = simulated_snapshot()
        oversized_html = copy.deepcopy(snapshot)
        oversized_html["business_limits"].append("x" * 3_700_000)
        self.assertLess(len(TOOL.json_bytes(oversized_html)), 4_800_000)
        oversized_json = copy.deepcopy(snapshot)
        oversized_json["extra"] = "\u00e9" * 2_400_000
        for value in (oversized_html, oversized_json):
            with temporary_cwd() as cwd, self.subTest(kind="HTML" if value is oversized_html else "JSON"):
                with self.assertRaises(TOOL.EvidenceError) as caught:
                    TOOL.write_report(value, BRANDING)
                self.assertEqual(caught.exception.code, "artifact_size_exceeded")
                self.assertEqual(list(cwd.iterdir()), [])

    def test_artifact_exact_boundary_and_default_json_transport_boundary(self):
        snapshot, _ = simulated_snapshot()
        with patch.object(TOOL, "render_html", return_value=b"x" * 4_800_000):
            self.assertEqual(len(TOOL.prepare_artifacts(snapshot, BRANDING)["report_path"]), 4_800_000)
        with patch.object(TOOL, "render_html", return_value=b"x" * 4_800_001):
            with self.assertRaises(TOOL.EvidenceError):
                TOOL.prepare_artifacts(snapshot, BRANDING)
        blank = {"unicode": "\u00e9", "padding": ""}
        blank["padding"] = "x" * (3500 - len(json.dumps(blank).encode("utf-8")))
        self.assertEqual(TOOL.response_size(blank), 3500)
        self.assertIs(TOOL.ensure_response(blank), blank)
        blank["padding"] += "x"
        with self.assertRaises(TOOL.EvidenceError):
            TOOL.ensure_response(blank)

    def test_transport_failure_also_precedes_directory_creation(self):
        snapshot, _ = simulated_snapshot()
        with temporary_cwd() as cwd, patch.object(TOOL, "TRANSPORT_BYTES", 20):
            with self.assertRaises(TOOL.EvidenceError) as caught:
                TOOL.write_report(snapshot, BRANDING)
            self.assertEqual(caught.exception.code, "transport_size_exceeded")
            self.assertEqual(list(cwd.iterdir()), [])

    def test_exclusive_atomic_write_failure_cleans_only_this_run_files(self):
        snapshot, _ = simulated_snapshot()
        original_link, calls = os.link, []
        def fail_second(source_path, target_path):
            calls.append(target_path)
            if len(calls) == 2:
                raise PermissionError("SIMULATED write denial")
            return original_link(source_path, target_path)
        with temporary_cwd() as cwd:
            directory = cwd / "azure-backup-reports"
            directory.mkdir()
            existing = directory / "unrelated.txt"
            existing.write_text("not this run", encoding="utf-8")
            with patch.object(TOOL.os, "link", side_effect=fail_second):
                with self.assertRaises(TOOL.EvidenceError) as caught:
                    TOOL.write_report(snapshot, BRANDING)
            self.assertEqual(caught.exception.code, "artifact_write_failed")
            self.assertEqual(list(directory.iterdir()), [existing])
            self.assertEqual(existing.read_text(), "not this run")

    def test_symlink_directory_and_filesystem_root_are_rejected(self):
        with temporary_cwd() as cwd:
            target = cwd / "actual"
            target.mkdir()
            try:
                (cwd / "azure-backup-reports").symlink_to(target, target_is_directory=True)
            except OSError:
                original = Path.is_symlink
                with patch.object(Path, "is_symlink", lambda path: path.name == "azure-backup-reports" or original(path)):
                    with self.assertRaises(TOOL.EvidenceError):
                        TOOL.artifact_directory()
            else:
                with self.assertRaises(TOOL.EvidenceError):
                    TOOL.artifact_directory()
        with patch.object(TOOL.Path, "cwd", return_value=Path(Path.cwd().anchor)):
            with self.assertRaises(TOOL.EvidenceError):
                TOOL.artifact_directory()

    def test_junction_output_flag_is_rejected_on_windows(self):
        if not hasattr(Path, "is_junction"):
            self.skipTest("Path.is_junction is not available on this Python/platform.")
        with temporary_cwd():
            original = Path.is_junction
            with patch.object(Path, "is_junction", lambda path: path.name == "azure-backup-reports" or original(path)):
                with self.assertRaises(TOOL.EvidenceError):
                    TOOL.artifact_directory()

    def test_native_links_only_for_exact_actual_runtime_shape_and_one_run(self):
        uid = "11111111-2222-4333-8444-555555555555"
        for prefix in ("/root/sreagent", "/usr"):
            root = PurePosixPath(prefix + "/terminalRoot/tmp/ThreadFiles/" + uid)
            stem = "backup-20261014T090000Z-abcdef123456"
            paths = {key: root / "azure-backup-reports" / (stem + suffix) for key, suffix in (
                ("report_path", ".html"), ("snapshot_path", ".json"), ("jobs_csv_path", "-jobs.csv"), ("coverage_csv_path", "-coverage.csv"))}
            result = TOOL.sharing_fields(root, paths)
            self.assertEqual(result["sharing_mode"], "native_ui")
            self.assertEqual(result["snapshot_url"], "/api/files/tmp/ThreadFiles/" + uid + "/azure-backup-reports/" + stem + ".json")
            self.assertFalse(result["http_verified"])
            invalid = dict(paths, snapshot_path=root / "escape.json")
            with self.assertRaises(TOOL.EvidenceError):
                TOOL.sharing_fields(root, invalid)
        for root in ("/tmp/demo", "/root/sreagent/terminalRoot/tmp/ThreadFiles/" + uid + "/subfolder",
                     "/usr/terminalRoot/tmp/ThreadFiles/not-a-uuid", "/root/sreagent/terminalRoot/tmp/ThreadFiles/" + "z"*36):
            self.assertEqual(TOOL.sharing_fields(PurePosixPath(root), {})["sharing_mode"], "local_files_only")

    def test_mocked_main_runs_real_adapter_and_writes_only_simulated_artifacts(self):
        reader = FakeReader()
        real_collect = TOOL.collect_snapshot
        def collect(*args):
            result = real_collect(*args)
            result["provenance"] = "SIMULATED"
            return result
        with temporary_cwd(), patch.object(TOOL, "validate_config", return_value=config()), patch.object(TOOL, "Identity") as identity, \
                patch.object(TOOL, "HttpReader", return_value=reader), patch.object(TOOL, "collect_snapshot", side_effect=collect), \
                patch.object(TOOL, "utc_now", return_value=REFERENCE):
            result = TOOL.main()
            self.assertEqual(result["artifact_status"], "written")
            self.assertEqual(result["provenance"], "SIMULATED")
            self.assertTrue(Path(result["snapshot_path"]).is_file())
            identity.return_value.close.assert_called_once()


class BrandingTests(unittest.TestCase):
    @staticmethod
    def raster(width=10, height=10, animated=False):
        from PIL import Image
        stream = io.BytesIO()
        image = Image.new("RGBA", (width, height), (251, 200, 7, 255))
        if animated:
            image.save(stream, format="PNG", save_all=True, append_images=[Image.new("RGBA", (width, height), "black")], duration=100, loop=0)
        else:
            image.save(stream, format="PNG")
        return stream.getvalue()

    def test_empty_branding_has_explicit_cliente_placeholder(self):
        branding = TOOL.validate_branding()
        self.assertEqual(branding, BRANDING)
        snapshot, _ = simulated_snapshot()
        rendered = TOOL.prepare_artifacts(snapshot, branding)["report_path"].decode("utf-8")
        self.assertIn('<span class="placeholder">CLIENTE<small>Customer logo</small></span>', rendered)
        self.assertIn("#FBC807", rendered)
        self.assertIn("#1E1C18", rendered)

    def test_real_pillow_validation_dimensions_bytes_single_frame_and_alt(self):
        raster = self.raster(width=2048, height=2)
        valid = "data:image/png;base64," + base64.b64encode(raster).decode()
        with patch.object(TOOL, "COMPANY_LOGO_DATA_URI", valid):
            self.assertEqual(TOOL.validate_branding()["logo"], valid)
        invalid = [
            "https://invalid.example/logo.png", "data:image/svg+xml;base64,PHN2Zz4=",
            "data:image/png;base64,not-base64", "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00"*24).decode(),
            "data:image/jpeg;base64," + base64.b64encode(raster).decode(),
            "data:image/png;base64," + base64.b64encode(self.raster(width=2049)).decode(),
            "data:image/png;base64," + base64.b64encode(self.raster(animated=True)).decode(),
            "data:image/png;base64," + base64.b64encode(self.raster()[:35]).decode(),
            "data:image/png;base64," + base64.b64encode(self.raster() + b"\x00"*100_001).decode(),
        ]
        for uri in invalid:
            with self.subTest(uri=uri[:70]), patch.object(TOOL, "COMPANY_LOGO_DATA_URI", uri):
                with self.assertRaises(TOOL.EvidenceError) as caught:
                    TOOL.validate_branding()
                self.assertEqual(caught.exception.code, "invalid_logo")
        with patch.object(TOOL, "COMPANY_LOGO_ALT_TEXT", "\ninvalid"):
            with self.assertRaises(TOOL.EvidenceError):
                TOOL.validate_branding()

    def test_invalid_logo_fails_before_source_collection_not_silent_fallback(self):
        with patch.object(TOOL, "COMPANY_LOGO_DATA_URI", "data:image/png;base64,YmFk"), \
                patch.object(TOOL, "Identity") as identity, patch.object(TOOL, "collect_snapshot") as collect:
            result = TOOL.main()
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error"]["code"], "invalid_logo")
            identity.assert_not_called()
            collect.assert_not_called()

    def test_truncated_decoder_setting_is_an_explicit_error(self):
        from PIL import ImageFile
        uri = "data:image/png;base64," + base64.b64encode(self.raster()).decode()
        with patch.object(ImageFile, "LOAD_TRUNCATED_IMAGES", True), patch.object(TOOL, "COMPANY_LOGO_DATA_URI", uri):
            with self.assertRaises(TOOL.EvidenceError) as caught:
                TOOL.validate_branding()
            self.assertEqual(caught.exception.code, "unsafe_decoder_settings")


if __name__ == "__main__":
    unittest.main()
