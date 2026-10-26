"""Opt-in OFFLINE normalization of an operator's recorded private preflight.

No identity, HTTP client, network, fake subscription read or fabricated details.
Only the caller's existing private file is read. Nothing here is a live collector.
"""

import copy
import hashlib
from urllib.parse import urlencode, urlsplit

from support import TOOL


def replay_document(document, fixture_bytes):
    if not isinstance(document, dict) or not isinstance(document.get("sources"), list):
        raise ValueError("Recorded preflight requires its complete source ledger.")
    reference = TOOL.parse_time(document.get("reference_utc"))
    if reference is None:
        raise ValueError("Recorded preflight requires its actual UTC reference.")
    vaults = document.get("approved_vault_ids_observed")
    if not isinstance(vaults, list) or not vaults or any(not isinstance(value, str) for value in vaults):
        raise ValueError("Recorded preflight requires its actual approved vault IDs.")
    window = TOOL.requested_window("last_14d", reference)
    config = {
        "subscription_id": document["subscription_id"], "tenant_id": document.get("identity", {}).get("tid"),
        "client_id": None,  # The supplied probe records oid, not the UAMI client ID.
        "vault_ids": vaults, "history": {},
    }
    sources, jobs, items, details = [], [], [], {}
    completed = []
    for index, record in enumerate(document["sources"]):
        if record.get("method") != "GET":
            raise ValueError("Replay accepts only recorded read-only source requests.")
        path = urlsplit(record["path"]).path
        folded = path.casefold()
        if "/backupjobs/" in folded:
            kind, scope = "job_details", path[:folded.index("/backupjobs/")]
        elif folded.endswith("/backupjobs"):
            kind, scope = "jobs", path[:-len("/backupJobs")]
        elif folded.endswith("/backupprotecteditems"):
            kind, scope = "protected_items", path[:-len("/backupProtectedItems")]
        elif folded.endswith("/providers/microsoft.recoveryservices/vaults"):
            kind, scope = "vault_inventory_list", document["subscription_id"]
        else:
            raise ValueError("Unsupported recorded preflight source; no invented adapter response.")
        if kind != "vault_inventory_list":
            matched = [vault for vault in vaults if vault.casefold() == scope.casefold()]
            if len(matched) != 1:
                raise ValueError("Recorded source is outside its approved full vault ID scope.")
            scope = matched[0]
        body = copy.deepcopy(record["body"])
        if not isinstance(body, dict):
            raise ValueError("Recorded native source body must be an object.")
        request_url = TOOL.ARM_ORIGIN + path + "?" + urlencode(record["parameters"])
        source_id = "recorded:" + str(index)
        receipt = TOOL.source_receipt(source_id, kind, scope, request_url, window if kind == "jobs" else None)
        receipt["recorded_probe"] = {
            key: record[key] for key in ("http", "requested_utc", "completed_utc", "first_page_only") if key in record
        }
        receipt["responses"] = [{"received_utc": record.get("completed_utc"), "request_url": request_url, "body": body}]
        receipt["records_received"] = len(body["value"]) if isinstance(body.get("value"), list) else 1
        receipt["pagination_complete"] = record["http"] == 200 and not body.get("nextLink")
        receipt["status"] = "complete" if receipt["pagination_complete"] else "partial"
        if record["http"] != 200:
            receipt["status"] = "denied" if record["http"] in (401, 403) else "error"
            receipt["errors"].append({"code": "recorded_http_error", "message": "Historical probe read failed.",
                                      "source": source_id, "http_status": record["http"]})
        elif body.get("nextLink"):
            receipt["errors"].append({"code": "replay_unread_continuation", "message": "Replay has no invented later page.",
                                      "source": source_id})
        if TOOL.parse_time(record.get("completed_utc")) is not None:
            completed.append(TOOL.parse_time(record["completed_utc"]))
        sources.append(receipt)
        if kind == "job_details" and isinstance(body.get("id"), str) and receipt["status"] == "complete":
            details[body["id"].casefold()] = (body, {"source_id": source_id, "page": 0, "row": None})
    for vault in vaults:
        scoped_jobs = [source for source in sources if source["kind"] == "jobs" and source["scope_id"].casefold() == vault.casefold()]
        scoped_items = [source for source in sources if source["kind"] == "protected_items" and source["scope_id"].casefold() == vault.casefold()]
        if len(scoped_jobs) != 1 or len(scoped_items) != 1:
            raise ValueError("Replay requires the actual recorded per-vault jobs/items reads.")
        for raw, ref in TOOL.records(scoped_items[0]):
            items.append(TOOL.normalize_item(raw, ref, vault))
        missing = []
        for raw, ref in TOOL.records(scoped_jobs[0]):
            identifier = raw.get("id") if isinstance(raw, dict) else None
            detail, detail_ref = details.get(identifier.casefold(), (None, None)) if isinstance(identifier, str) else (None, None)
            jobs.append(TOOL.normalize_job(raw, ref, detail, detail_ref, vault, window, "complete" if detail else "not_recorded"))
            if detail is None:
                missing.append(identifier)
        if missing:
            gap = TOOL.source_receipt("recorded:missing-details:" + str(len(sources)), "job_details_not_recorded", vault, "")
            gap.update(status="not_collected", pending_job_ids=missing)
            gap["errors"].append({"code": "replay_not_recorded", "message": "Only recorded detail bodies exist; no responses were fabricated.",
                                  "source": gap["source_id"]})
            sources.append(gap)
    snapshot = TOOL.finish_snapshot(config, window, sources, jobs, items, provenance="RECORDED_REPLAY")
    snapshot["collection_finished_utc"] = TOOL.iso(max(completed)) if completed else document["reference_utc"]
    snapshot["replay"] = {
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(), "recorded_reference_utc": document["reference_utc"],
        "replayed_utc": TOOL.iso(TOOL.utc_now()), "not_fresh_live_validation": True,
        "first_page_probe_not_complete_collection": document.get("first_page_probe_not_complete_collection"),
        "recorded_identity_claims": document.get("identity"), "uami_client_id_not_in_probe": True,
        "note": "Historical private source normalization only; no fresh collection or invented unrecorded job details.",
    }
    return snapshot
