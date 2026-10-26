"""Read existing Azure Backup evidence; write four complete offline workpapers."""

import base64
import binascii
import csv
import hashlib
import html
import io
import json
import math
import os
import re
import ssl
import tempfile
import time
import warnings
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from uuid import UUID, uuid4


SUBSCRIPTION_ID = "<YOUR_SUBSCRIPTION_ID>"
TENANT_ID = "<YOUR_TENANT_ID>"
MANAGED_IDENTITY_CLIENT_ID = "<YOUR_AGENT_CLIENT_ID>"
APPROVED_VAULT_IDS = ["<APPROVED_RECOVERY_SERVICES_VAULT_RESOURCE_ID>"]
CLIENT_NAME = "CLIENTE"
# The customer's authorized logo goes HERE, privately, as short adjacent Python
# string literals containing one data:image/png;base64,... or JPEG data URI.
# Keep generic Git source empty. Never paste a real customer logo into Git.
COMPANY_LOGO_DATA_URI = ""
COMPANY_LOGO_ALT_TEXT = "Customer logo"
# Optional operator-verified source-availability intervals, NOT job min/max dates.
# Key: full approved vault ID. Value: from_utc, through_utc, evidence (receipt).
# Leave empty until that exact historical availability has actually been verified.
VERIFIED_HISTORY = {}

ARM_ORIGIN = "https://management.azure.com"
BACKUP_API_VERSION = "2026-10-01"
VAULT_API_VERSION = "2026-07-01"
SUBSCRIPTION_API_VERSION = "2022-12-01"
OUTPUT_DIRECTORY = "azure-backup-reports"
ARTIFACT_BYTES = 4_800_000
TRANSPORT_BYTES = 3_500
MAX_PAGES = 100
MAX_ROWS = 10_000
MAX_DETAIL_READS = 1_000
MAX_HTTP_ATTEMPTS = 2_500
MAX_HTTP_BYTES = 4_800_000
MAX_COLLECTION_SECONDS = 240
UTC = timezone.utc


class EvidenceError(RuntimeError):
    def __init__(self, code, message, source, http_status=None, artifacts_may_remain=False):
        super().__init__(message)
        self.code, self.message, self.source = code, message, source
        self.http_status = http_status
        self.artifacts_may_remain = artifacts_may_remain

    def public(self):
        result = {"code": self.code, "message": self.message, "source": self.source}
        if self.http_status is not None:
            result["http_status"] = self.http_status
        return result


def utc_now():
    return datetime.now(UTC)


def iso(value):
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value):
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def guid(value, field):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value.lower() or UUID(value).int == 0:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise EvidenceError("configuration_required", "Configure " + field + " with its explicit GUID.", "configuration") from exc
    return value.lower()


def plain(value, field, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or re.search(r"[\x00-\x1f\x7f]", value):
        raise EvidenceError("invalid_configuration", field + " must be a bounded, nonempty plain string.", "configuration")
    return value.strip()


def validate_config():
    config = {
        "subscription_id": guid(SUBSCRIPTION_ID, "SUBSCRIPTION_ID"),
        "tenant_id": guid(TENANT_ID, "TENANT_ID"),
        "client_id": guid(MANAGED_IDENTITY_CLIENT_ID, "MANAGED_IDENTITY_CLIENT_ID"),
    }
    if not isinstance(APPROVED_VAULT_IDS, list) or not 1 <= len(APPROVED_VAULT_IDS) <= 10:
        raise EvidenceError("configuration_required", "Configure one to ten explicitly approved Recovery Services vault IDs.", "configuration")
    vaults = []
    for value in APPROVED_VAULT_IDS:
        if not isinstance(value, str) or not re.fullmatch(
            r"/subscriptions/" + re.escape(config["subscription_id"])
            + r"/resourceGroups/[A-Za-z0-9_.()-]{1,90}/providers/Microsoft\.RecoveryServices/vaults/[A-Za-z0-9-]{2,50}",
            value, re.IGNORECASE,
        ):
            raise EvidenceError("configuration_required", "Each allowed vault must be a full Recovery Services ID in the fixed subscription.", "configuration")
        vaults.append(value)
    if len({value.casefold() for value in vaults}) != len(vaults):
        raise EvidenceError("invalid_configuration", "Approved vault IDs must be unique, case-insensitively.", "configuration")
    if not isinstance(VERIFIED_HISTORY, dict):
        raise EvidenceError("invalid_configuration", "VERIFIED_HISTORY must be an explicit per-vault evidence mapping.", "configuration")
    histories = {}
    for vault_id, record in VERIFIED_HISTORY.items():
        if not isinstance(vault_id, str) or vault_id.casefold() not in {value.casefold() for value in vaults}:
            raise EvidenceError("invalid_configuration", "History evidence must name an approved full vault ID.", "configuration")
        if not isinstance(record, dict) or set(record) != {"from_utc", "through_utc", "evidence"}:
            raise EvidenceError("invalid_configuration", "History evidence requires from_utc, through_utc and an actual receipt description.", "configuration")
        start, end = parse_time(record["from_utc"]), parse_time(record["through_utc"])
        if start is None or end is None or start >= end:
            raise EvidenceError("invalid_configuration", "History evidence must have an ordered, explicit-offset interval.", "configuration")
        plain(record["evidence"], "History receipt", 500)
        histories[vault_id.casefold()] = dict(record)
    config.update(vault_ids=vaults, history=histories)
    return config


def validate_branding():
    name = plain(CLIENT_NAME, "CLIENT_NAME", 120)
    alt = plain(COMPANY_LOGO_ALT_TEXT, "COMPANY_LOGO_ALT_TEXT", 120)
    uri = COMPANY_LOGO_DATA_URI
    if uri == "":
        return {"name": name, "logo": "", "alt": alt}
    if not isinstance(uri, str) or len(uri) > 133_370:
        raise EvidenceError("invalid_logo", "Use a bounded inline PNG/JPEG raster, not a URL or path.", "branding")
    match = re.fullmatch(r"data:image/(png|jpeg);base64,([A-Za-z0-9+/]+={0,2})", uri)
    if match is None:
        raise EvidenceError("invalid_logo", "Logo MIME/base64 must describe one inline PNG or JPEG.", "branding")
    try:
        data = base64.b64decode(match[2], validate=True)
    except binascii.Error as exc:
        raise EvidenceError("invalid_logo", "Logo base64 is invalid.", "branding") from exc
    if base64.b64encode(data).decode("ascii") != match[2] or not 1 <= len(data) <= 100_000:
        raise EvidenceError("invalid_logo", "Logo must be canonical base64 for 1..100000 raster bytes.", "branding")
    try:
        from PIL import Image, ImageFile, UnidentifiedImageError
    except ImportError as exc:
        raise EvidenceError("dependency_missing", "Configured branding requires Pillow raster validation before collection.", "branding") from exc
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise EvidenceError("unsafe_decoder_settings", "Truncated-image decoding must be disabled.", "branding")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=["PNG", "JPEG"]) as image:
                if (
                    image.format != ("PNG" if match[1] == "png" else "JPEG")
                    or getattr(image, "n_frames", 1) != 1
                    or not 1 <= image.width <= 2048 or not 1 <= image.height <= 2048
                ):
                    raise EvidenceError("invalid_logo", "Logo requires one matching PNG/JPEG frame, at most 2048px per dimension.", "branding")
                image.verify()
            with Image.open(io.BytesIO(data), formats=["PNG", "JPEG"]) as image:
                image.load()
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise EvidenceError("invalid_logo", "Logo is not a complete decodable single-frame PNG/JPEG raster.", "branding") from exc
    return {"name": name, "logo": uri, "alt": alt}


def requested_window(period, reference):
    if not isinstance(period, str) or period not in ("last_14d", "last_24h"):
        raise EvidenceError("invalid_parameter", "period must be last_14d or last_24h; full previous-month reporting is not implemented.", "parameters")
    if reference.tzinfo is None or reference.utcoffset() is None:
        raise EvidenceError("invalid_reference", "Collection reference must be timezone aware.", "window")
    reference = reference.astimezone(UTC).replace(microsecond=0)
    return {
        "period": period, "start_utc": iso(reference - timedelta(days=14 if period == "last_14d" else 1)),
        "end_utc": iso(reference), "boundary": "[start,end)",
        "selection": "Native job startTime; not end-time overlap or all historical in-progress jobs.",
        "cadence_is_not_coverage": True,
    }


def backup_filter_time(value):
    value = value.astimezone(UTC)
    return value.strftime("%Y-%m-%d %I:%M:%S ") + ("AM" if value.hour < 12 else "PM")


def source_receipt(source_id, kind, scope, url, window=None):
    return {
        "source_id": source_id, "kind": kind, "scope_id": scope, "request_url": url,
        "status": "not_collected", "requested_window": window, "responses": [],
        "records_received": 0, "pagination_complete": False, "errors": [],
    }


def source_error(source, exc):
    source["errors"].append(exc.public())
    source["status"] = "partial" if source["responses"] else "denied" if exc.http_status in (401, 403) else "error"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Identity:
    def __init__(self, config):
        try:
            from azure.identity import ManagedIdentityCredential
        except ImportError as exc:
            raise EvidenceError("dependency_missing", "Install azure-identity for the explicitly configured UAMI; no other credential fallback.", "identity") from exc
        self.config = config
        self.credential = ManagedIdentityCredential(client_id=config["client_id"])

    def token(self):
        from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError
        from azure.identity import CredentialUnavailableError
        try:
            token = self.credential.get_token(ARM_ORIGIN + "/.default").token
        except (ClientAuthenticationError, CredentialUnavailableError, ServiceRequestError) as exc:
            raise EvidenceError("authentication_failed", "The configured managed identity could not acquire the ARM token.", "identity") from exc
        try:
            encoded = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        except (AttributeError, IndexError, ValueError, binascii.Error, UnicodeDecodeError) as exc:
            raise EvidenceError("authentication_failed", "Token identity claims could not be checked; no token content is retained.", "identity") from exc
        if not isinstance(claims, dict) or not (
            isinstance(claims.get("tid"), str) and claims["tid"].lower() == self.config["tenant_id"]
            and isinstance(claims.get("appid") or claims.get("azp"), str)
            and (claims.get("appid") or claims.get("azp")).lower() == self.config["client_id"]
            and isinstance(claims.get("aud"), str)
            and claims["aud"].rstrip("/") in (ARM_ORIGIN, "https://management.core.windows.net")
        ):
            raise EvidenceError("identity_mismatch", "Token tenant/client/audience does not match the fixed ARM identity.", "identity")
        return token

    def close(self):
        self.credential.close()


def next_link(link, initial):
    if not isinstance(link, str) or not link or len(link) > 24_000 or re.search(r"[\x00-\x1f\x7f]", link):
        raise EvidenceError("unsafe_pagination", "Continuation must be a bounded absolute HTTPS ARM URL.", "pagination")
    try:
        current, first = urlsplit(link), urlsplit(initial)
        if (
            current.scheme != "https" or current.netloc.casefold() != "management.azure.com"
            or current.username or current.password or current.fragment or current.port not in (None, 443)
            or unquote(current.path).casefold() != unquote(first.path).casefold()
            or "\\" in unquote(current.path)
            or any(part in (".", "..") for part in unquote(current.path).split("/"))
        ):
            raise ValueError
        pairs = parse_qsl(current.query, keep_blank_values=True, strict_parsing=True)
        original = dict(parse_qsl(first.query, keep_blank_values=True, strict_parsing=True))
    except (ValueError, TypeError) as exc:
        raise EvidenceError("unsafe_pagination", "Continuation changed HTTPS origin, exact vault/collection path or query syntax.", "pagination") from exc
    folded = [key.casefold() for key, _ in pairs]
    values = dict(pairs)
    allowed_paging = {"$skiptoken", "skiptoken"}
    if len(set(folded)) != len(folded) or len([key for key in folded if key in allowed_paging]) > 1:
        raise EvidenceError("unsafe_pagination", "Continuation repeats/conflicts on a query parameter.", "pagination")
    if any(key not in original and key.casefold() not in allowed_paging for key in values):
        raise EvidenceError("unsafe_pagination", "Continuation added an unapproved query parameter.", "pagination")
    if any(values.get(key) != value for key, value in original.items()):
        raise EvidenceError("unsafe_pagination", "Continuation changed/omitted the API version or time filter.", "pagination")
    if not any(key.casefold() in allowed_paging and value for key, value in pairs):
        raise EvidenceError("unsafe_pagination", "Continuation omitted a nonempty native skip token.", "pagination")
    return link


class HttpReader:
    def __init__(self, identity, config):
        self.identity, self.config = identity, config
        self.deadline = time.monotonic() + MAX_COLLECTION_SECONDS
        self.attempts = 0
        self.allowed = {}
        context = ssl.create_default_context()
        self.opener = build_opener(NoRedirect(), HTTPSHandler(context=context))

    def allow(self, url):
        parsed = urlsplit(url)
        subscription = "/subscriptions/" + self.config["subscription_id"]
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        path = unquote(parsed.path)
        valid = path.casefold() == subscription.casefold() and query == {"api-version": SUBSCRIPTION_API_VERSION}
        for vault in self.config["vault_ids"]:
            base = vault.casefold()
            if path.casefold() == base:
                valid = query == {"api-version": VAULT_API_VERSION}
            elif path.casefold() in (base + "/backupjobs", base + "/backupprotecteditems"):
                valid = query.get("api-version") == BACKUP_API_VERSION and set(query) <= {"api-version", "$filter"}
            elif re.fullmatch(re.escape(base) + r"/backupjobs/[a-z0-9_.()-]{1,256}", path.casefold()):
                valid = query == {"api-version": BACKUP_API_VERSION}
        if not (
            valid and parsed.scheme == "https" and parsed.netloc == "management.azure.com"
            and not parsed.fragment and not parsed.username and not parsed.password
            and "\\" not in path and not any(part in (".", "..") for part in path.split("/"))
            and len(query) == len(parse_qsl(parsed.query, keep_blank_values=True))
        ):
            raise EvidenceError("unsafe_endpoint", "Only the fixed subscription/vault GET read contracts are allowed.", "http")
        self.allowed[parsed.path.casefold()] = url
        return url

    def request(self, url, source):
        parsed = urlsplit(url)
        initial = self.allowed.get(parsed.path.casefold())
        if initial is None or (url != initial and next_link(url, initial) != url):
            raise EvidenceError("unsafe_endpoint", "Request is not an explicitly allowlisted read or validated continuation.", source)
        for attempt in range(3):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or self.attempts >= MAX_HTTP_ATTEMPTS:
                raise EvidenceError("collection_bound", "Shared collection time/request bound reached; remaining reads are not collected.", source)
            self.attempts += 1
            request = Request(url, method="GET", headers={
                "Accept": "application/json", "Authorization": "Bearer " + self.identity.token(),
            })
            try:
                with self.opener.open(request, timeout=max(0.01, min(30, remaining))) as response:
                    if response.status != 200:
                        raise EvidenceError("http_error", "Read did not return HTTP 200.", source, response.status)
                    raw = response.read(MAX_HTTP_BYTES + 1)
                    if len(raw) > MAX_HTTP_BYTES:
                        raise EvidenceError("response_bound", "Native response exceeded the byte safety bound; no truncated body was accepted.", source)
            except HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                    retry = exc.headers.get("Retry-After", "") if exc.headers else ""
                    delay = min(int(retry), 5) if re.fullmatch(r"[0-9]{1,4}", retry) else attempt + 1
                    if time.monotonic() + delay >= self.deadline:
                        raise EvidenceError("collection_bound", "Retry would exceed the collection time bound.", source) from exc
                    time.sleep(delay)
                    continue
                raise EvidenceError("access_denied" if exc.code in (401, 403) else "http_error",
                                    "Read returned HTTP " + str(exc.code) + "; authentication headers and error bodies are excluded.",
                                    source, exc.code) from exc
            except (URLError, OSError, TimeoutError, ssl.SSLError) as exc:
                raise EvidenceError("transport_failed", "TLS/transport failed; no alternate identity, insecure retry or redirect.", source) from exc
            try:
                result = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            except (ValueError, UnicodeDecodeError, RecursionError) as exc:
                raise EvidenceError("invalid_json", "Native response is not finite, valid JSON.", source) from exc
            if not isinstance(result, dict):
                raise EvidenceError("invalid_response", "Native response must be an object.", source)
            return result
        raise EvidenceError("http_error", "Read retries exhausted.", source)


def read_one(reader, source):
    try:
        reader.allow(source["request_url"])
        body = reader.request(source["request_url"], source["source_id"])
        source["responses"].append({"received_utc": iso(utc_now()), "request_url": source["request_url"], "body": body})
        source.update(status="complete", records_received=1, pagination_complete=True)
        return body
    except EvidenceError as exc:
        source_error(source, exc)
        return None


def read_pages(reader, source):
    initial, seen, identities = source["request_url"], set(), set()
    current = initial
    try:
        reader.allow(initial)
        for _ in range(MAX_PAGES):
            if current in seen:
                raise EvidenceError("pagination_loop", "Native continuation repeated a page.", source["source_id"])
            seen.add(current)
            body = reader.request(current, source["source_id"])
            source["responses"].append({"received_utc": iso(utc_now()), "request_url": current, "body": body})
            page = body.get("value")
            if not isinstance(page, list):
                raise EvidenceError("invalid_response", "List response lacks an explicit value array; not an empty-success read.", source["source_id"])
            source["records_received"] += len(page)
            for row in page:
                identity = row.get("id") if isinstance(row, dict) else None
                if isinstance(identity, str) and identity:
                    if identity.casefold() in identities:
                        source_error(source, EvidenceError("duplicate_identity", "Native identity repeated; all received records are retained.", source["source_id"]))
                    identities.add(identity.casefold())
            continuation = body.get("nextLink")
            if continuation is None:
                total = body.get("totalCount")
                if total is not None and (type(total) is not int or total != source["records_received"]):
                    raise EvidenceError("missing_continuation", "Declared total does not reconcile with received rows.", source["source_id"])
                if any(body.get(key) in (True, "true", "True") for key in ("truncated", "isTruncated", "resultTruncated")):
                    raise EvidenceError("missing_continuation", "Source declares truncation without continuation.", source["source_id"])
                source.update(status="partial" if source["errors"] else "complete", pagination_complete=True)
                return
            if source["records_received"] >= MAX_ROWS:
                raise EvidenceError("row_bound", "Row safety bound reached after retaining the entire received page; continuation remains unread.", source["source_id"])
            current = next_link(continuation, initial)
        raise EvidenceError("page_bound", "Page bound reached; all prior pages are retained and coverage is partial.", source["source_id"])
    except EvidenceError as exc:
        source_error(source, exc)


def records(source):
    for page_index, response in enumerate(source["responses"]):
        value = response["body"].get("value")
        if isinstance(value, list):
            for row_index, row in enumerate(value):
                yield row, {"source_id": source["source_id"], "page": page_index, "row": row_index}


def native_record(sources_by_id, reference):
    response = sources_by_id[reference["source_id"]]["responses"][reference["page"]]["body"]
    return response if reference.get("row") is None else response["value"][reference["row"]]


def object_properties(raw):
    return raw.get("properties") if isinstance(raw, dict) and isinstance(raw.get("properties"), dict) else {}


def native_text(value):
    return value if isinstance(value, str) and value else None


def state_category(value):
    if not isinstance(value, str):
        return "unknown"
    compact = re.sub(r"[\s_-]", "", value).casefold()
    return {
        "failed": "failed", "completedwithwarnings": "warning", "completedwithwarning": "warning",
        "warning": "warning", "warnings": "warning", "inprogress": "in_progress",
        "completed": "completed", "cancelled": "cancelled", "canceled": "cancelled",
    }.get(compact, "unknown")


def operation_group(value):
    if not isinstance(value, str):
        return "unknown"
    return {"backup": "backup", "restore": "restore", "delete": "delete",
            "deletebackupdata": "delete"}.get(value.casefold(), "other")


def duration_seconds(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?", value)
    if match is None or all(part is None for part in match.groups()):
        return None
    result = sum(float(part or 0) * factor for part, factor in zip(match.groups(), (86400, 3600, 60, 1)))
    return result if math.isfinite(result) else None


def temporal_membership(start, window):
    parsed = parse_time(start)
    if parsed is None:
        return "unknown"
    return "in_requested_window" if parse_time(window["start_utc"]) <= parsed < parse_time(window["end_utc"]) else "outside_requested_window"


def valid_job_id(value, vault_id):
    return isinstance(value, str) and re.fullmatch(
        re.escape(vault_id) + r"/backupJobs/[A-Za-z0-9_.()-]{1,256}", value, re.IGNORECASE,
    ) is not None


def normalize_job(raw, ref, detail, detail_ref, vault_id, window, detail_status):
    listed, observed = object_properties(raw), object_properties(detail)
    # Keep list and later detail observations distinct; do not overwrite evidence.
    effective = {**listed, **observed}
    native_status = native_text(effective.get("status"))
    start = effective.get("startTime")
    end = effective.get("endTime")
    notes = []
    identifier = raw.get("id") if isinstance(raw, dict) else None
    if not valid_job_id(identifier, vault_id):
        notes.append("Missing/out-of-scope native job ID; no detail URL was constructed.")
    if not listed:
        notes.append("Missing/object-invalid list properties; original row is retained.")
    if parse_time(start) is None:
        notes.append("Missing/invalid startTime: window membership is Unknown.")
    if end is not None and parse_time(end) is None:
        notes.append("Invalid native endTime retained.")
    if parse_time(start) is not None and parse_time(end) is not None and parse_time(end) < parse_time(start):
        notes.append("Native endTime precedes startTime; duration is not inferred.")
    native_duration = effective.get("duration")
    return {
        "record_key": ref["source_id"] + ":" + str(ref["page"]) + ":" + str(ref["row"]),
        "id": identifier, "vault_id": vault_id, "vault_name": vault_id.rsplit("/", 1)[-1],
        "name": raw.get("name") if isinstance(raw, dict) else None,
        "entity_name": native_text(effective.get("entityFriendlyName")),
        "native_status": native_status, "list_status": listed.get("status"), "detail_status": observed.get("status"),
        "state_category": state_category(native_status),
        "state_changed": "status" in observed and observed.get("status") != listed.get("status"),
        "operation": native_text(effective.get("operation")), "operation_group": operation_group(effective.get("operation")),
        "backup_management_type": effective.get("backupManagementType"), "workload_type": effective.get("workloadType"),
        "job_type": effective.get("jobType"), "source_resource_type": effective.get("dataSourceType"),
        "start_time": start, "end_time": end, "duration_native": native_duration,
        "duration_seconds": duration_seconds(native_duration), "window_membership": temporal_membership(start, window),
        "native_item_id_candidates": [], "matched_item_id": None, "association_status": "not_established",
        "association_evidence": [], "source_resource_matches": [], "is_user_triggered": effective.get("isUserTriggered"),
        "native_issue_evidence_paths": [
            {"observation": origin, "json_pointer": "/properties" + pointer}
            for origin, props in (("list_ref", listed), ("detail_ref", observed))
            for pointer, value in string_leaves(props)
            if value and re.search(r"error|warning", pointer, re.IGNORECASE)
        ],
        "list_ref": ref, "detail_ref": detail_ref, "details_collection_status": detail_status,
        "validation_notes": notes,
    }


def normalize_item(raw, ref, vault_id):
    props = object_properties(raw)
    identifier = raw.get("id") if isinstance(raw, dict) else None
    valid_id = isinstance(identifier, str) and identifier.casefold().startswith(vault_id.casefold() + "/") and "/protecteditems/" in identifier.casefold()
    return {
        "record_key": ref["source_id"] + ":" + str(ref["page"]) + ":" + str(ref["row"]),
        "id": identifier, "vault_id": vault_id, "vault_name": vault_id.rsplit("/", 1)[-1],
        "name": props.get("friendlyName"), "source_resource_id": props.get("sourceResourceId"),
        "backup_management_type": props.get("backupManagementType"), "workload_type": props.get("workloadType"),
        "protected_item_type": props.get("protectedItemType"), "policy_id": props.get("policyId"),
        "policy_name": props.get("policyName"), "protection_state": props.get("protectionState"),
        "protection_status": props.get("protectionStatus"), "health_status": props.get("healthStatus"),
        "last_backup_status": props.get("lastBackupStatus"), "last_backup_time": props.get("lastBackupTime"),
        "last_recovery_point": props.get("lastRecoveryPoint"), "source_ref": ref,
        "identity_valid": valid_id, "matched_backup_job_records": 0, "job_association_status": "no_exact_job_link_observed",
        "expected_backup_jobs": None, "missed_backup_jobs": None, "policy_schedule_evaluated": False,
        "validation_notes": [] if valid_id and props else ["Native item ID/properties need review; the entire original row is retained."],
    }


def string_leaves(value, pointer=""):
    if isinstance(value, str):
        yield pointer, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from string_leaves(child, pointer + "/" + key.replace("~", "~0").replace("/", "~1"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from string_leaves(child, pointer + "/" + str(index))


def associate_items(jobs, items, sources):
    by_source = {source["source_id"]: source for source in sources}
    for job in jobs:
        evidence, candidates, source_matches = [], set(), []
        scoped = [item for item in items if item["identity_valid"] and item["vault_id"].casefold() == job["vault_id"].casefold()]
        lookup, resource_lookup = {}, {}
        for item in scoped:
            lookup.setdefault(item["id"].casefold(), []).append(item)
            value = item.get("source_resource_id")
            if isinstance(value, str) and value.casefold().startswith("/subscriptions/"):
                resource_lookup.setdefault(value.casefold(), []).append(item)
        for origin in ("list_ref", "detail_ref"):
            if job[origin] is None:
                continue
            raw = native_record(by_source, job[origin])
            for pointer, value in string_leaves(object_properties(raw)):
                if value.casefold().startswith(job["vault_id"].casefold() + "/") and "/protecteditems/" in value.casefold():
                    candidates.add(value)
                for item in lookup.get(value.casefold(), []):
                    evidence.append({"item_id": item["id"], "basis": "exact_native_protected_item_id", "observation": origin,
                                     "json_pointer": "/properties" + pointer, "native_value": value})
                for item in resource_lookup.get(value.casefold(), []):
                    source_matches.append({"item_id": item["id"], "source_resource_id": value, "observation": origin,
                                           "json_pointer": "/properties" + pointer, "not_an_item_identity": True})
        identifiers = {entry["item_id"].casefold() for entry in evidence}
        job["native_item_id_candidates"] = sorted(candidates)
        job["association_evidence"] = evidence
        job["source_resource_matches"] = source_matches
        if len(identifiers) == 1:
            identifier = next(iter(identifiers))
            job["matched_item_id"] = next(entry["item_id"] for entry in evidence if entry["item_id"].casefold() == identifier)
            job["association_status"] = "exact_full_id_match"
            for item in scoped:
                if item["id"].casefold() == identifier and job["operation_group"] == "backup" and job["window_membership"] == "in_requested_window":
                    item["matched_backup_job_records"] += 1
                    item["job_association_status"] = "exact_linked_records_observed"
        elif len(identifiers) > 1:
            job["association_status"] = "ambiguous_full_id_matches"
        elif source_matches:
            job["association_status"] = "source_resource_id_is_not_item_identity"


def history_coverage(vault_id, window, verified, jobs, job_source):
    start, end = parse_time(window["start_utc"]), parse_time(window["end_utc"])
    evidence = verified.get(vault_id.casefold())
    intervals, gaps = [], []
    if evidence:
        left = max(start, parse_time(evidence["from_utc"]))
        right = min(end, parse_time(evidence["through_utc"]))
        if left < right:
            intervals.append({"start_utc": iso(left), "end_utc": iso(right)})
            if start < left:
                gaps.append({"start_utc": iso(start), "end_utc": iso(left), "status": "unverified"})
            if right < end:
                gaps.append({"start_utc": iso(right), "end_utc": iso(end), "status": "unverified"})
    if not intervals:
        gaps = [{"start_utc": iso(start), "end_utc": iso(end), "status": "unknown"}]
    dates = [parse_time(job["start_time"]) for job in jobs if job["vault_id"].casefold() == vault_id.casefold() and parse_time(job["start_time"]) is not None]
    return {
        "vault_id": vault_id, "requested_window": window, "verified_available_intervals": intervals,
        "unverified_or_unknown_intervals": gaps, "availability_evidence": evidence,
        "history_status": "verified_interval" if not gaps else "partial_verified_interval" if intervals else "unknown",
        "query_status": job_source["status"], "pagination_complete": job_source["pagination_complete"],
        "observed_job_start_min": iso(min(dates)) if dates else None,
        "observed_job_start_max": iso(max(dates)) if dates else None,
        "observed_span_is_not_retention": True, "rest_retention_days": None,
        "note": "Paged REST query completion is not verified retention. ARG's documented 14 days is not a universal REST limit.",
    }


def build_review(jobs, items, sources, history):
    review = []
    for job in jobs:
        categories = {state_category(job["list_status"]), state_category(job["detail_status"]), job["state_category"]}
        reason, severity = None, "Unknown"
        if "failed" in categories:
            reason, severity = "Native Failed observed; review the list/detail timeline and source error evidence.", "Error"
        elif "warning" in categories:
            reason, severity = "Native warning observed; review warning/error/task details without relabeling Completed.", "Warning"
        elif job["state_category"] in ("cancelled", "in_progress"):
            reason, severity = "Observed " + str(job["native_status"]) + "; no overdue or missed-schedule conclusion is inferred.", "Attention"
        elif job["native_issue_evidence_paths"]:
            reason, severity = "Native error/warning text is present; inspect it without overriding the native job state.", "Attention"
        elif job["state_category"] == "unknown" or job["validation_notes"] or job["details_collection_status"] != "complete":
            reason = "State, dates or job details need evidence review; not a synthesized failed job."
        if reason:
            review.append({"kind": "job", "severity": severity, "record_key": job["record_key"], "resource_id": job["id"],
                           "vault_id": job["vault_id"], "reason": reason, "operation": job["operation"],
                           "window_membership": job["window_membership"], "incident_status": "not_created"})
    for item in items:
        category = state_category(item["last_backup_status"])
        if category in ("failed", "warning") or item["validation_notes"]:
            review.append({"kind": "protected_item", "severity": "Error" if category == "failed" else "Warning" if category == "warning" else "Unknown",
                           "record_key": item["record_key"], "resource_id": item["id"], "vault_id": item["vault_id"],
                           "reason": "Review native item metadata separately from windowed jobs; it is a current snapshot, not a missed-job finding.",
                           "incident_status": "not_created"})
    for source in sources:
        if source["status"] != "complete":
            review.append({"kind": "source", "severity": "Unknown", "source_id": source["source_id"],
                           "vault_id": source["scope_id"], "resource_id": source["scope_id"],
                           "reason": "Source is " + source["status"] + "; received pages remain available. See the source ledger.",
                           "incident_status": "not_created"})
    for row in history:
        if row["history_status"] != "verified_interval":
            review.append({"kind": "history", "severity": "Unknown", "vault_id": row["vault_id"], "resource_id": row["vault_id"],
                           "reason": "Requested history is not fully verified; job min/max dates cannot establish continuous availability.",
                           "incident_status": "not_created"})
    return review


def finish_snapshot(config, window, sources, jobs, items, provenance="LIVE"):
    associate_items(jobs, items, sources)
    history = []
    for vault in config["vault_ids"]:
        source = next(row for row in sources if row["scope_id"] == vault and row["kind"] == "jobs")
        history.append(history_coverage(vault, window, config["history"], jobs, source))
    review = build_review(jobs, items, sources, history)
    backup = [row for row in jobs if row["operation_group"] == "backup" and row["window_membership"] == "in_requested_window"]
    all_in_window = [row for row in jobs if row["window_membership"] == "in_requested_window"]
    source_issues = sum(row["status"] != "complete" for row in sources)
    unknown_history = sum(row["history_status"] != "verified_interval" for row in history)
    return {
        "schema_version": "azure-backup-operations-v1", "tool_name": "generate-azure-backup-report",
        "provenance": provenance, "reference_utc": window["end_utc"], "collection_finished_utc": iso(utc_now()),
        "requested_window": window, "scope": {"subscription_id": config["subscription_id"], "tenant_id": config["tenant_id"],
            "managed_identity_client_id": config["client_id"], "approved_vault_ids": config["vault_ids"]},
        "sources": sources, "jobs": jobs, "protected_items": items, "history_coverage": history, "human_review": review,
        "summary": {
            "job_records_received": len(jobs), "unique_job_ids": len({row["id"].casefold() for row in jobs if isinstance(row["id"], str)}),
            "job_records_in_window": len(all_in_window), "backup_job_records_in_window": len(backup),
            "other_operation_records_in_window": len(all_in_window) - len(backup),
            "backup_native_states": dict(Counter(row["native_status"] or "Unknown (missing)" for row in backup)),
            "backup_state_categories": dict(Counter(row["state_category"] for row in backup)),
            "unknown_time_records": sum(row["window_membership"] == "unknown" for row in jobs),
            "outside_window_records": sum(row["window_membership"] == "outside_requested_window" for row in jobs),
            "observed_protected_item_records": len(items), "expected_protected_items": None, "expected_backup_jobs": None,
            "missed_backup_jobs": None, "source_issues": source_issues, "history_unverified_vaults": unknown_history,
            "human_review_records": len(review), "protection_coverage_percentage": None,
        },
        "assessment_status": "partial" if source_issues or unknown_history else "read_complete",
        "limits": {"page_cap_per_list": MAX_PAGES, "row_bound_per_list": MAX_ROWS, "detail_read_cap": MAX_DETAIL_READS,
                   "collection_seconds": MAX_COLLECTION_SECONDS, "http_attempt_cap": MAX_HTTP_ATTEMPTS,
                   "source_response_bytes": MAX_HTTP_BYTES, "artifact_bytes": ARTIFACT_BYTES},
        "business_limits": [
            "No observed jobs is not proof that all backups succeeded.",
            "Completed does not demonstrate recoverability, backup integrity, restore testing or RPO/RTO.",
            "Observed protected items are not the expected protection denominator; policy schedules and intent were not evaluated.",
            "Restore, Delete and other operations are preserved separately from Backup.",
            "No incident/ticket was created, attached, updated or closed. This is a human review queue.",
            "14 days is this tool's bounded recent review window, not a universal REST retention limit.",
            "Protected-item metadata and lastBackupTime are current observations, not a historical month or an expected occurrence.",
        ],
    }


def collect_snapshot(reader, config, period, reference):
    window = requested_window(period, reference)
    sources, jobs, items = [], [], []
    subscription = source_receipt("subscription", "subscription", config["subscription_id"],
        ARM_ORIGIN + "/subscriptions/" + config["subscription_id"] + "?api-version=" + SUBSCRIPTION_API_VERSION)
    body = read_one(reader, subscription)
    if body is None:
        raise EvidenceError("subscription_unverified", "The fixed Enabled subscription/tenant could not be verified; no report collection was accepted.", "subscription")
    if not (
        isinstance(body.get("subscriptionId"), str) and body["subscriptionId"].lower() == config["subscription_id"]
        and isinstance(body.get("tenantId"), str) and body["tenantId"].lower() == config["tenant_id"]
        and body.get("state") == "Enabled"
    ):
        raise EvidenceError("subscription_mismatch", "Subscription must be Enabled and belong to the fixed tenant.", "subscription")
    sources.append(subscription)
    details_read, detail_cache = 0, {}
    for index, vault in enumerate(config["vault_ids"]):
        prefix = "vault:" + str(index)
        inventory = source_receipt(prefix + ":inventory", "vault_inventory", vault, ARM_ORIGIN + vault + "?api-version=" + VAULT_API_VERSION)
        sources.append(inventory)
        metadata = read_one(reader, inventory)
        if metadata is not None and (not isinstance(metadata.get("id"), str) or metadata["id"].casefold() != vault.casefold()):
            source_error(inventory, EvidenceError("vault_identity_mismatch", "Vault metadata did not match the exact approved ID.", inventory["source_id"]))
        protected = source_receipt(prefix + ":items", "protected_items", vault,
            ARM_ORIGIN + vault + "/backupProtectedItems?api-version=" + BACKUP_API_VERSION)
        sources.append(protected)
        read_pages(reader, protected)
        for raw, ref in records(protected):
            item = normalize_item(raw, ref, vault)
            items.append(item)
            if item["validation_notes"]:
                source_error(protected, EvidenceError("invalid_item_metadata", "Item metadata needs review; raw row remains in the complete export.", protected["source_id"]))
        # This API's time-range filter uses 12-hour AM/PM text in UTC, not ISO
        # strings. The report and every original source date remain ISO/native.
        time_filter = "startTime eq '" + backup_filter_time(parse_time(window["start_utc"])) + "' and endTime eq '" + backup_filter_time(parse_time(window["end_utc"])) + "'"
        job_source = source_receipt(prefix + ":jobs", "jobs", vault,
            ARM_ORIGIN + vault + "/backupJobs?" + urlencode({"api-version": BACKUP_API_VERSION, "$filter": time_filter}), window)
        sources.append(job_source)
        read_pages(reader, job_source)
        capped = []
        for raw, ref in records(job_source):
            identifier = raw.get("id") if isinstance(raw, dict) else None
            detail, detail_ref, detail_status = None, None, "not_collected"
            if valid_job_id(identifier, vault):
                if identifier.casefold() in detail_cache:
                    detail, detail_ref, detail_status = detail_cache[identifier.casefold()]
                elif details_read < MAX_DETAIL_READS:
                    details_read += 1
                    source_id = prefix + ":detail:" + str(details_read)
                    detail_source = source_receipt(source_id, "job_details", vault, ARM_ORIGIN + identifier + "?api-version=" + BACKUP_API_VERSION)
                    sources.append(detail_source)
                    observed = read_one(reader, detail_source)
                    if observed is not None:
                        observed_id = observed.get("id")
                        if not isinstance(observed_id, str) or observed_id.casefold() != identifier.casefold():
                            source_error(detail_source, EvidenceError("job_identity_mismatch", "Job detail ID changed; raw response retained but not merged.", source_id))
                        elif not isinstance(observed.get("properties"), dict):
                            source_error(detail_source, EvidenceError("invalid_job_details", "Job details lack object properties; raw response retained.", source_id))
                        else:
                            detail, detail_ref = observed, {"source_id": source_id, "page": 0, "row": None}
                    detail_status = detail_source["status"]
                    detail_cache[identifier.casefold()] = (detail, detail_ref, detail_status)
                else:
                    capped.append(identifier)
            job = normalize_job(raw, ref, detail, detail_ref, vault, window, detail_status)
            jobs.append(job)
            if job["validation_notes"]:
                source_error(job_source, EvidenceError("invalid_job_metadata", "Job ID/dates/properties need review; raw evidence is preserved.", job_source["source_id"]))
        if capped:
            cap = source_receipt(prefix + ":details_not_collected", "job_details_bound", vault, "")
            cap.update(status="not_collected", pending_job_ids=capped)
            cap["errors"].append(EvidenceError("detail_bound", "Detail-read cap reached; listed jobs were not dropped or replaced.", cap["source_id"]).public())
            sources.append(cap)
    return finish_snapshot(config, window, sources, jobs, items)


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def response_size(value):
    return len(json.dumps(value, allow_nan=False).encode("utf-8"))


def ensure_response(value):
    if response_size(value) > TRANSPORT_BYTES:
        raise EvidenceError("transport_size_exceeded", "Default-serialized result exceeds 3500 bytes; no truncated result or files were produced.", "transport")
    return value


def csv_cell(value):
    if value is None:
        return ""
    text = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) if isinstance(value, (dict, list)) else str(value)
    return "'" + text if re.match(r"^[\s\ufeff\x00-\x1f\x7f]*[=+\-@]", text) else text


def csv_bytes(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(fields)
    for row in rows:
        writer.writerow([csv_cell(row.get(field)) for field in fields])
    return stream.getvalue().encode("utf-8-sig")


def export_csvs(snapshot):
    by_id = {source["source_id"]: source for source in snapshot["sources"]}
    jobs = []
    for row in snapshot["jobs"]:
        jobs.append({**row, "provenance": snapshot["provenance"], "reference_utc": snapshot["reference_utc"],
                     "requested_start_utc": snapshot["requested_window"]["start_utc"],
                     "requested_end_utc": snapshot["requested_window"]["end_utc"],
                     "native_list_json": native_record(by_id, row["list_ref"]),
                     "native_detail_json": native_record(by_id, row["detail_ref"]) if row["detail_ref"] else None})
    job_fields = (
        "provenance", "reference_utc", "requested_start_utc", "requested_end_utc", "record_key", "id", "vault_id",
        "vault_name", "name", "entity_name", "native_status", "list_status", "detail_status", "state_category",
        "state_changed", "operation", "operation_group", "backup_management_type", "workload_type", "job_type",
        "source_resource_type", "start_time", "end_time", "duration_native", "duration_seconds", "window_membership",
        "native_item_id_candidates", "matched_item_id", "association_status", "association_evidence", "source_resource_matches", "is_user_triggered",
        "native_issue_evidence_paths", "list_ref", "detail_ref", "details_collection_status", "validation_notes", "native_list_json", "native_detail_json",
    )
    coverage = []
    for item in snapshot["protected_items"]:
        coverage.append({"record_type": "protected_item", "provenance": snapshot["provenance"],
                         "reference_utc": snapshot["reference_utc"], "vault_id": item["vault_id"], "resource_id": item["id"],
                         **item, "full_record_json": item, "native_source_json": native_record(by_id, item["source_ref"])})
    for source in snapshot["sources"]:
        coverage.append({"record_type": "source_ledger", "provenance": snapshot["provenance"],
                         "reference_utc": snapshot["reference_utc"], "vault_id": source["scope_id"],
                         "resource_id": source["scope_id"], "source_id": source["source_id"], "source_status": source["status"],
                         "full_record_json": source})
    for record in snapshot["history_coverage"]:
        coverage.append({"record_type": "history_coverage", "provenance": snapshot["provenance"],
                         "reference_utc": snapshot["reference_utc"], "vault_id": record["vault_id"], "resource_id": record["vault_id"],
                         "source_status": record["history_status"], "full_record_json": record})
    coverage_fields = (
        "record_type", "provenance", "reference_utc", "record_key", "vault_id", "vault_name", "resource_id", "id", "name",
        "source_resource_id", "backup_management_type", "workload_type", "protected_item_type", "policy_id", "policy_name",
        "protection_state", "protection_status", "health_status", "last_backup_status", "last_backup_time",
        "last_recovery_point", "identity_valid", "matched_backup_job_records", "job_association_status",
        "expected_backup_jobs", "missed_backup_jobs", "policy_schedule_evaluated", "validation_notes",
        "source_ref", "source_id", "source_status", "full_record_json", "native_source_json",
    )
    return csv_bytes(jobs, job_fields), csv_bytes(coverage, coverage_fields)


def artifact_directory():
    try:
        cwd = Path.cwd()
        root = cwd.resolve(strict=True)
        linked = any(path.is_symlink() or getattr(path, "is_junction", lambda: False)() for path in (cwd, *cwd.parents))
    except (OSError, RuntimeError) as exc:
        raise EvidenceError("unsafe_artifact_root", "Actual cwd must resolve to an existing real directory.", "artifact_storage") from exc
    if linked or root == Path(root.anchor) or not root.is_dir():
        raise EvidenceError("unsafe_artifact_root", "Filesystem roots and linked/junction cwd ancestors are forbidden.", "artifact_storage")
    if OUTPUT_DIRECTORY != "azure-backup-reports":
        raise EvidenceError("unsafe_artifact_directory", "Only the fixed azure-backup-reports child is allowed.", "artifact_storage")
    directory = root / OUTPUT_DIRECTORY
    if directory.is_symlink() or getattr(directory, "is_junction", lambda: False)() or directory.resolve() != directory:
        raise EvidenceError("unsafe_artifact_directory", "Output directory cannot be linked or escape actual cwd.", "artifact_storage")
    return root, directory


def sharing_fields(root, paths):
    result = {"sharing_mode": "local_files_only", "http_verified": False}
    match = re.fullmatch(r"/(?:root/sreagent|usr)/terminalRoot/tmp/ThreadFiles/([0-9a-fA-F-]{36})", root.as_posix())
    if match is None:
        return result
    try:
        if str(UUID(match[1])) != match[1].lower():
            return result
    except ValueError:
        return result
    suffixes = {"report_path": ".html", "snapshot_path": ".json", "jobs_csv_path": "-jobs.csv", "coverage_csv_path": "-coverage.csv"}
    if set(paths) != set(suffixes):
        raise EvidenceError("unsafe_sharing_path", "Native sharing requires exactly this run's four complete files.", "artifact_storage")
    stem = paths["report_path"].stem
    if not re.fullmatch(r"(?:backup|simulated|replay)-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}", stem):
        raise EvidenceError("unsafe_sharing_path", "Native sharing requires generated run filenames.", "artifact_storage")
    for key, suffix in suffixes.items():
        path = paths[key]
        if path.parent != root / OUTPUT_DIRECTORY or path.name != stem + suffix:
            raise EvidenceError("unsafe_sharing_path", "Native sharing must reference one run inside the fixed cwd child.", "artifact_storage")
        result[key.removesuffix("_path") + "_url"] = (
            "/api/files/tmp/ThreadFiles/" + match[1] + "/" + OUTPUT_DIRECTORY + "/" + quote(path.name, safe="")
        )
    result["sharing_mode"] = "native_ui"
    return result


def prepare_artifacts(snapshot, branding):
    document = json_bytes(snapshot)
    if len(document) > ARTIFACT_BYTES:
        raise EvidenceError("artifact_size_exceeded", "Complete JSON exceeds 4800000 bytes; no fields/rows were dropped and no files were written.", "artifact_storage")
    jobs_csv, coverage_csv = export_csvs(snapshot)
    rendered = render_html(snapshot, document, jobs_csv, coverage_csv, branding)
    data = {"report_path": rendered, "snapshot_path": document, "jobs_csv_path": jobs_csv, "coverage_csv_path": coverage_csv}
    if any(len(value) > ARTIFACT_BYTES for value in data.values()):
        raise EvidenceError("artifact_size_exceeded", "A complete plain HTML/JSON/CSV exceeds 4800000 bytes; no lossy fallback or files were written.", "artifact_storage")
    return data


def write_report(snapshot, branding):
    root, directory = artifact_directory()
    prefix = {"SIMULATED": "simulated-", "LIVE": "backup-", "RECORDED_REPLAY": "replay-"}.get(snapshot["provenance"])
    if prefix is None:
        raise EvidenceError("invalid_provenance", "Evidence must explicitly distinguish live, simulated and recorded replay.", "artifact_storage")
    stem = prefix + snapshot["reference_utc"].replace("-", "").replace(":", "") + "-" + uuid4().hex[:12]
    paths = {key: directory / (stem + suffix) for key, suffix in (
        ("report_path", ".html"), ("snapshot_path", ".json"), ("jobs_csv_path", "-jobs.csv"), ("coverage_csv_path", "-coverage.csv"))}
    data = prepare_artifacts(snapshot, branding)
    result = ensure_response({
        "status": "partial" if snapshot["assessment_status"] == "partial" else "ok", "provenance": snapshot["provenance"],
        "artifact_status": "written", "reference_utc": snapshot["reference_utc"], "requested_window": {
            key: snapshot["requested_window"][key] for key in ("period", "start_utc", "end_utc", "boundary")},
        "counts": snapshot["summary"], **sharing_fields(root, paths), **{key: str(path) for key, path in paths.items()},
        "artifact_bytes": {key.removesuffix("_path"): len(value) for key, value in data.items()},
        "snapshot_sha256": hashlib.sha256(data["snapshot_path"]).hexdigest(),
        "notice": "Unknown denominators/history are not healthy zeroes. Monthly is cadence. See complete files for source errors and human review; no incidents were created.",
    })
    temporary, written = [], []
    try:
        directory.mkdir(exist_ok=True)
        if artifact_directory()[1] != directory or directory.resolve(strict=True) != directory or not directory.is_dir():
            raise EvidenceError("unsafe_artifact_directory", "Output directory changed after preparation.", "artifact_storage")
        for key, content in data.items():
            if artifact_directory()[1] != directory:
                raise EvidenceError("unsafe_artifact_directory", "Output directory changed during writing.", "artifact_storage")
            fd, filename = tempfile.mkstemp(prefix=stem + "-", suffix=".tmp", dir=directory)
            path = Path(filename)
            temporary.append(path)
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            # Atomic, exclusive publication: unlike replace(), never overwrite a
            # colliding file, even if it appears after the existence check.
            os.link(path, paths[key])
            written.append(paths[key])
            path.unlink()
            temporary.remove(path)
        if any(path.read_bytes() != data[key] for key, path in paths.items()):
            raise EvidenceError("artifact_readback_failed", "Written bytes do not reconcile with all prepared artifacts.", "artifact_storage")
    except (OSError, EvidenceError) as exc:
        failures = []
        for path in temporary + written:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                failures.append(path.name)
        if failures:
            raise EvidenceError("artifact_cleanup_failed", "Write/readback failed and this run's generated files could not all be removed.", "artifact_storage", artifacts_may_remain=True) from exc
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError("artifact_write_failed", "Could not exclusively publish/read back all four artifacts; partial files from this run were removed.", "artifact_storage") from exc
    return result


HTML_TEMPLATE = r"""<!doctype html>
<!--
THESIS: A backup shift workpaper puts the observable window before the outcome; it refuses a success-score dashboard.
OWN-WORLD: Supplied-pixel yellow #FBC807, charcoal #1E1C18, neutral evidence sheets, system sans and ruled ledgers. Brand is not warning severity.
STORY: Qualify scope and history, inspect native job states and errors, review item evidence, then make a human decision.
FIRST VIEWPORT: Charcoal mast with yellow customer frame, sparse yellow navigation, a wide window/coverage sheet and complete-file actions; job filters follow immediately.
FORM: Brief-pinned Operate workpaper, not a new identity tournament. Inline disclosure is the signature interaction; desktop rows become labeled mobile records.
-->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'; object-src 'none'">
<title>Azure Backup | Operations review</title>
<style>
:root{
  color-scheme:light;--brand:#FBC807;--charcoal:#1E1C18;--canvas:#F2F4F5;--sheet:#FFFFFF;
  --ink:#24272B;--muted:#535D66;--line:#CCD2D7;--field:#6C7680;--wash:#F6F8F9;
  --error:#A51E29;--error-wash:#FFF0F1;--warning:#854400;--warning-wash:#FFF4E9;
  --unknown:#4F5971;--unknown-wash:#F0F2F8;--complete:#276442;--complete-wash:#EEF7F1;
  --active:#175A83;--active-wash:#EDF5FA;--radius:3px
}
*{box-sizing:border-box}
html{scroll-behavior:auto;scroll-padding-top:20px}
body{margin:0;background:var(--canvas);color:var(--ink);font:16px/1.5 "Segoe UI",system-ui,sans-serif;overflow-wrap:anywhere}
[hidden]{display:none!important}
a{color:#18577D;text-underline-offset:3px}
button,input,select{font:inherit;min-height:44px;border:1px solid var(--field);border-radius:var(--radius);background:var(--sheet);color:var(--ink);padding:8px 12px;max-width:100%}
button{cursor:pointer;font-weight:600}
button:hover:not(:disabled),input:hover,select:hover{background:#EDF0F2}
button:active:not(:disabled){background:#DCE2E6}
button:disabled{cursor:not-allowed;color:#636C75;background:#E8ECEF}
button.primary{background:var(--brand);border-color:var(--charcoal);color:var(--charcoal)}
button.primary:hover:not(:disabled){background:#EDB900}
button,input,select,a,summary{touch-action:manipulation}
:focus-visible{outline:3px solid #18577D;outline-offset:3px}
.skip{position:absolute;top:-100px;left:16px;z-index:4;background:var(--sheet);padding:12px 20px}
.skip:focus{top:12px}
.mast{background:var(--charcoal);color:#FFFFFF}
.mast-inner{max-width:1552px;margin:auto;padding:28px 32px;display:grid;grid-template-columns:190px minmax(0,1fr) auto;gap:28px;align-items:center}
.brand-frame{background:var(--brand);color:var(--charcoal);border:1px solid var(--brand);padding:14px;min-height:92px;display:flex;align-items:center;justify-content:center}
.brand-frame img{display:block;max-width:100%;max-height:64px;width:auto;height:auto;object-fit:contain}
.placeholder{font-size:22px;font-weight:750;line-height:1.2;letter-spacing:.02em;text-align:center}
.placeholder small{display:block;font-size:12px;letter-spacing:0;font-weight:500;margin-top:9px}
h1{font-size:30px;line-height:1.2;letter-spacing:-.02em;margin:0 0 10px;font-weight:650;text-wrap:balance}
.mast p{color:#D7D5D0;margin:0;max-width:68ch}
.stamp{font-size:13px;text-align:right;max-width:240px}
.stamp strong{display:block;color:var(--brand);font-size:14px;margin-bottom:6px}
.navigation{background:var(--brand);color:var(--charcoal)}
.navigation-inner{max-width:1552px;margin:auto;display:flex;gap:4px;padding:0 28px;flex-wrap:wrap}
.navigation a{padding:12px;color:var(--charcoal);font-weight:600;text-decoration:none;min-height:48px;border-bottom:3px solid transparent}
.navigation a:hover,.navigation a:focus-visible{background:#EDB900;border-bottom-color:var(--charcoal)}
main{max-width:1552px;margin:auto;padding:28px 32px 48px;min-width:0}
section{scroll-margin-top:20px;margin-bottom:28px;background:var(--sheet);border:1px solid var(--line);padding:28px;min-width:0}
h2{font-size:24px;line-height:1.3;letter-spacing:-.015em;margin:0 0 12px;font-weight:650;text-wrap:balance}
h3{font-size:18px;line-height:1.35;margin:28px 0 12px;font-weight:650}
p{margin:0 0 12px;max-width:75ch}
.muted,.note{color:var(--muted);font-size:14px}
.intro{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(260px,1fr);gap:32px}
.intro-actions{padding-left:28px;border-left:1px solid var(--line)}
.intro-actions h3{margin-top:0}
.downloads{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}
.downloads button{font-size:14px}
.facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px 24px;margin:20px 0}
.facts div{min-width:0}
dt{font-size:13px;color:var(--muted);margin-bottom:4px}
dd{margin:0;font-weight:600;font-variant-numeric:tabular-nums}
.notice{padding:14px 16px;border:1px solid var(--unknown);background:var(--unknown-wash);color:var(--unknown);margin:20px 0 0;font-size:14px;max-width:none}
.notice.error{border-color:var(--error);background:var(--error-wash);color:var(--error)}
.count-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;margin:24px 0 0;padding-top:20px;border-top:1px solid var(--line)}
.count-strip dd{font-size:23px}
.section-head{display:flex;align-items:start;justify-content:space-between;gap:20px}
.section-head p{font-size:14px;color:var(--muted)}
fieldset{margin:20px 0;padding:16px;border:1px solid var(--line);background:var(--wash);min-width:0}
legend{padding:0 8px;font-weight:600;font-size:14px}
.filters{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px 18px}
label{display:flex;flex-direction:column;gap:6px;font-size:14px;font-weight:600;min-width:0}
label select,label input{width:100%;font-weight:400;min-width:0}
.filter-footer{display:flex;align-items:center;gap:16px;justify-content:space-between;margin-top:16px}
.filter-footer p{margin:0}
.filters-summary{font-size:14px;color:var(--muted);margin:12px 0}
.table-region{overflow:auto;max-width:100%;border:1px solid var(--line)}
table{border-collapse:collapse;width:100%;table-layout:fixed}
caption{text-align:left;font-size:14px;color:var(--muted);padding:12px;background:var(--wash);border-bottom:1px solid var(--line)}
th{text-align:left;font-size:13px;font-weight:650;color:var(--muted);background:var(--wash)}
td,th{padding:12px;vertical-align:top;border-bottom:1px solid var(--line);overflow-wrap:anywhere}
td{font-size:14px}
tbody tr:last-child td{border-bottom:0}
td strong{font-weight:650}
td small{display:block;color:var(--muted);font-size:12px;line-height:1.5;margin-top:5px}
td time{display:block;font-variant-numeric:tabular-nums}
.jobs-table th:nth-child(1){width:25%}
.jobs-table th:nth-child(2){width:16%}
.jobs-table th:nth-child(3){width:17%}
.jobs-table th:nth-child(4){width:21%}
.jobs-table th:nth-child(5){width:21%}
.pill{display:inline-block;padding:3px 8px;border:1px solid currentColor;font-size:12px;font-weight:650;border-radius:var(--radius);margin-bottom:4px}
.pill.failed,.pill.Error,.pill.denied,.pill.error{color:var(--error);background:var(--error-wash)}
.pill.warning,.pill.Warning,.pill.partial{color:var(--warning);background:var(--warning-wash)}
.pill.completed,.pill.complete{color:var(--complete);background:var(--complete-wash)}
.pill.in_progress,.pill.Attention{color:var(--active);background:var(--active-wash)}
.pill.unknown,.pill.Unknown,.pill.cancelled,.pill.not_collected{color:var(--unknown);background:var(--unknown-wash)}
details{min-width:0}
summary{cursor:pointer;color:#18577D;font-weight:600;min-height:44px;padding:8px 0}
summary:hover{text-decoration:underline}
pre{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;font:12px/1.6 Consolas,monospace;background:var(--wash);border:1px solid var(--line);padding:12px;max-height:440px;overflow:auto;margin:8px 0}
.evidence-block{margin-top:12px}
.evidence-block h4{font-size:14px;margin:12px 0 6px}
.empty{padding:28px 20px;border:1px dashed var(--field);background:var(--wash);margin:16px 0;color:var(--muted)}
.pager{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-top:16px}
.pager p{margin:0;font-size:14px;color:var(--muted)}
.pager-controls{display:flex;gap:8px;flex-wrap:wrap;max-width:100%}
.queue{display:grid;gap:0}
.review-record{padding:18px 0;border-bottom:1px solid var(--line)}
.review-record:last-child{border-bottom:0;padding-bottom:0}
.review-record:first-child{padding-top:0}
.review-title{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:6px}
.review-record p{font-size:14px;margin-bottom:6px}
.identity{font-size:12px;color:var(--muted)}
.history-table th:nth-child(1){width:23%}
.history-table th:nth-child(2){width:25%}
.history-table th:nth-child(3){width:30%}
.history-table th:nth-child(4){width:22%}
.source-table th:nth-child(1){width:25%}
.source-table th:nth-child(2){width:17%}
.source-table th:nth-child(3){width:20%}
.source-table th:nth-child(4){width:38%}
.item-table th:nth-child(1){width:28%}
.item-table th:nth-child(2){width:24%}
.item-table th:nth-child(3){width:21%}
.item-table th:nth-child(4){width:27%}
.limits-list{padding-left:20px;font-size:14px;max-width:85ch}
.limits-list li{margin:8px 0}
.hash{font:12px/1.6 Consolas,monospace;overflow-wrap:anywhere;max-width:none}
footer{max-width:1488px;margin:0 auto 32px;padding:0 32px;color:var(--muted);font-size:13px}
footer p{max-width:90ch}
@media(max-width:1000px){
  .mast-inner{grid-template-columns:160px minmax(0,1fr);gap:20px}
  .stamp{grid-column:2;text-align:left;max-width:none}
  .intro{grid-template-columns:1fr}
  .intro-actions{padding:20px 0 0;border-left:0;border-top:1px solid var(--line)}
  .count-strip{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:640px){
  .mast-inner{padding:22px 18px;grid-template-columns:1fr;gap:18px}
  .brand-frame{max-width:190px;min-height:76px}
  .stamp{grid-column:auto}
  h1{font-size:26px}
  .navigation-inner{padding:0 8px;gap:0}
  .navigation a{padding:11px 10px;font-size:14px}
  main{padding:18px 12px 24px}
  section{padding:20px 16px;margin-bottom:18px}
  h2{font-size:21px}
  .facts,.filters{grid-template-columns:1fr;gap:14px}
  .count-strip{gap:16px}
  .count-strip dt{font-size:12px}
  .section-head{display:block}
  .section-head button{margin-top:8px}
  fieldset{padding:12px}
  .filter-footer{align-items:start;flex-direction:column}
  .downloads{display:grid;grid-template-columns:1fr}
  .table-region{overflow:visible}
  table,tbody,thead,tr,td,th,caption{display:block;width:auto!important}
  thead{position:absolute;width:1px!important;height:1px;overflow:hidden;clip-path:inset(50%)}
  tbody tr{padding:8px 0;border-bottom:1px solid var(--field)}
  tbody tr:last-child{border:0}
  tbody td{border:0;display:grid;grid-template-columns:82px minmax(0,1fr);gap:10px;padding:8px 12px}
  tbody td::before{content:attr(data-label);font-size:12px;font-weight:650;color:var(--muted)}
  footer{padding:0 18px}
}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important;animation:none!important}}
@media print{
  @page{size:landscape;margin:12mm}
  body{background:#FFFFFF;font-size:10pt}
  .mast{print-color-adjust:exact;-webkit-print-color-adjust:exact}
  .mast-inner{padding:16px;grid-template-columns:150px minmax(0,1fr) 230px}
  .stamp{grid-column:auto;text-align:right}
  h1{font-size:23pt}
  .navigation,.downloads,.pager-controls,.filter-footer button,.section-head button,.skip{display:none!important}
  main{padding:12px 0;max-width:none}
  section{padding:14px;margin-bottom:18px;break-inside:auto}
  .intro{grid-template-columns:1.5fr 1fr;gap:20px}
  .intro-actions{padding:0 0 0 20px;border-top:0;border-left:1px solid var(--line)}
  .filters{grid-template-columns:repeat(3,minmax(0,1fr))}
  fieldset{display:none}
  .count-strip{grid-template-columns:repeat(4,minmax(0,1fr))}
  .table-region{overflow:visible}
  table{table-layout:fixed}
  tr,.review-record{break-inside:avoid}
  thead{display:table-header-group}
  td,th{padding:7px;font-size:9pt}
  pre{max-height:none;overflow:visible;font-size:8pt}
  summary{min-height:0;padding:4px 0}
  details{break-inside:auto}
  button{display:none}
  footer{padding:0}
}
</style>
</head>
<body>
<a class="skip" href="#main">Skip to evidence</a>
<header class="mast">
  <div class="mast-inner">
    <div class="brand-frame" aria-label="Customer branding">__LOGO__</div>
    <div><h1>Azure Backup operations</h1><p>Existing jobs. Native evidence. A human decision.</p><p id="client-name">__CLIENT__</p></div>
    <div class="stamp"><strong id="provenance">DATED OFFLINE SNAPSHOT</strong><span id="reference">Opening recorded evidence</span></div>
  </div>
</header>
<nav class="navigation" aria-label="Report sections"><div class="navigation-inner">
  <a href="#window">Window &amp; scope</a><a href="#jobs">Jobs</a><a href="#review">Human review</a><a href="#items">Items &amp; coverage</a><a href="#sources">Sources</a>
</div></nav>
<main id="main" tabindex="-1">
<noscript><section><h2>JavaScript is disabled</h2><p>This offline report needs local JavaScript for filters and disclosure. Use the accompanying full JSON and ordinary CSV files. No live source is queried by this page.</p></section></noscript>
<section id="opening" role="status"><h2>Opening the complete local snapshot</h2><p>No network request or live polling is performed.</p></section>
<section id="fatal" hidden role="alert"><h2>Evidence could not be opened</h2><p id="fatal-message"></p><p>Use the accompanying JSON/CSV files and report this artifact failure. Do not interpret this view as an empty or successful backup review.</p></section>
<div id="report" hidden>
<section id="window">
  <div class="intro">
    <div>
      <h2>Read the window before the result</h2>
      <p>This is a review of observed operations, not a protection or recovery certification. Monthly is the review cadence, not the amount of available history.</p>
      <dl class="facts">
        <div><dt>Requested start, inclusive (UTC)</dt><dd id="requested-start"></dd></div>
        <div><dt>Requested end, exclusive (UTC)</dt><dd id="requested-end"></dd></div>
        <div><dt>Fixed approved vaults</dt><dd id="vault-count"></dd></div>
        <div><dt id="finished-label">Current collection finished (UTC)</dt><dd id="finished"></dd></div>
      </dl>
      <p id="coverage-notice" class="notice"></p>
    </div>
    <div class="intro-actions">
      <h3>Keep the whole workpaper</h3>
      <p class="note">Downloads always include every received record and source, regardless of filters or the visible page. Full JSON is the exact embedded UTF-8 byte sequence, not a reserialized display model.</p>
      <div class="downloads">
        <button type="button" class="primary" id="export-json" disabled>Full source JSON</button>
        <button type="button" id="export-jobs" disabled>All jobs CSV</button>
        <button type="button" id="export-coverage" disabled>Items / coverage CSV</button>
        <button type="button" id="print" disabled>Print matching evidence</button>
      </div>
      <p class="note">No incident/ticket, attachment or closure is created here. Review decisions remain with IT Operations.</p>
      <details><summary>Scope and source boundaries</summary><pre id="scope-text"></pre></details>
    </div>
  </div>
  <dl class="count-strip">
    <div><dt>Backup records in requested window</dt><dd id="backup-count"></dd></div>
    <div><dt>Restore / Delete / other records</dt><dd id="other-count"></dd></div>
    <div><dt>Observed protected-item records</dt><dd id="item-count"></dd></div>
    <div><dt>Expected protection denominator</dt><dd>Unknown</dd></div>
  </dl>
</section>
<section id="jobs">
  <div class="section-head"><div><h2>Native job ledger</h2><p>List and later JobDetails observations remain separate. Failed, warnings, InProgress, Completed, Cancelled and unknown states are not merged into a success rate.</p></div><button type="button" id="today">Focus last 24 hours</button></div>
  <fieldset><legend>Filter this snapshot</legend><div class="filters">
    <label for="vault-filter">Vault (full-ID scope)<select id="vault-filter"></select></label>
    <label for="window-filter">Job-start window<select id="window-filter">
      <option value="requested">Requested interval</option><option value="last24">Last 24 hours at collection</option>
      <option value="today">Today UTC at collection</option><option value="unknown">Unknown start time</option><option value="all">All received source rows</option>
    </select></label>
    <label for="state-filter">Native state (any observation)<select id="state-filter"></select></label>
    <label for="operation-filter">Native operation<select id="operation-filter"></select></label>
    <label for="item-filter">Exactly linked protected item<select id="item-filter"></select></label>
    <label for="job-filter">Job ID / entity text<input id="job-filter" type="search" maxlength="512" autocomplete="off" placeholder="Filter the recorded jobs"></label>
  </div><div class="filter-footer"><p class="note">Vault selection also filters items, history, review and sources. Other controls filter jobs only; they never hide source blind spots. Counts above always describe the full approved scope.</p><button type="button" id="reset">Reset filters</button></div></fieldset>
  <p class="filters-summary" id="filter-summary" aria-live="polite"></p>
  <p class="note" id="retained-note"></p>
  <div id="jobs-empty" class="empty" hidden>No matching job records. This does not establish that no backup was required or that all backups succeeded. Check window, source access, paging and item coverage.</div>
  <div class="table-region" id="jobs-region" role="region" aria-label="Native job records" tabindex="0">
    <table class="jobs-table"><caption>Native dates and duration are retained; missing values are Unknown. Expand Evidence for original list/detail properties and errors.</caption>
      <thead><tr><th scope="col">Job / entity</th><th scope="col">Native state</th><th scope="col">Operation / workload</th><th scope="col">UTC dates / duration</th><th scope="col">Source evidence</th></tr></thead><tbody id="jobs-body"></tbody>
    </table>
  </div>
  <div class="pager"><p id="page-note"></p><div class="pager-controls"><button type="button" id="previous">Previous records</button><button type="button" id="next">Next records</button></div></div>
</section>
<section id="review">
  <h2>Human review, not incidents</h2>
  <p class="note">Native failures/warnings, unfinished/cancelled work, unknown metadata and source/history blind spots. Job candidates respect the selected vault and job-start window; source/history uncertainty remains visible. No invented SLA or overdue threshold.</p>
  <p class="filters-summary" id="review-note"></p><div class="queue" id="review-records"></div>
</section>
<section id="items">
  <h2>Item coverage without an invented denominator</h2>
  <p>These are the protected items actually returned by the permitted source, not the list of everything that should be protected. A policy ID is not an evaluated schedule. No friendly-name join is used.</p>
  <h3>Requested versus verified history</h3>
  <div class="table-region" role="region" aria-label="History coverage by vault" tabindex="0"><table class="history-table">
    <caption>Observed job min/max dates are a span of returned records, never proof of continuous history or retention. ARG's 14-day job history is not a universal REST limit.</caption>
    <thead><tr><th scope="col">Approved vault</th><th scope="col">Requested / observed</th><th scope="col">Verified availability / gaps</th><th scope="col">Read evidence</th></tr></thead><tbody id="history-body"></tbody>
  </table></div>
  <h3>Observed protected items</h3>
  <p class="note">An exact full-ID job association can be absent or ambiguous. Zero exact links does not establish a missed backup. Current lastBackupStatus/lastRecoveryPoint metadata is not a restore or integrity test.</p>
  <div id="items-empty" class="empty" hidden>No protected-item records were returned for this selection. This is not proof of an empty expected scope; inspect each source receipt.</div>
  <div class="table-region" id="items-region" role="region" aria-label="Observed protected items" tabindex="0"><table class="item-table">
    <caption>Expected jobs, missed occurrences and intended protection coverage remain Unknown; policy schedules/intent were not evaluated.</caption>
    <thead><tr><th scope="col">Item / source identity</th><th scope="col">Native protection metadata</th><th scope="col">Latest native dates</th><th scope="col">Association / evidence</th></tr></thead><tbody id="items-body"></tbody>
  </table></div>
</section>
<section id="sources">
  <h2>Source and pagination ledger</h2>
  <p class="note">A received HTTP 200 is a read receipt, not a Completed job. Explicit empty arrays, denied reads, malformed responses and partial paging remain different. Every received page, including pages preceding an error, stays in the full JSON and coverage CSV.</p>
  <p class="filters-summary" id="source-note"></p>
  <div class="table-region" role="region" aria-label="Source receipts" tabindex="0"><table class="source-table">
    <caption>Expand each source for original response fields, native error/warning evidence, request path, collection UTC and any sanitized transport errors. Headers and tokens are excluded.</caption>
    <thead><tr><th scope="col">Source / scope</th><th scope="col">Read status</th><th scope="col">Pages / records</th><th scope="col">Receipt / original fields</th></tr></thead><tbody id="sources-body"></tbody>
  </table></div>
</section>
<section id="limits"><h2>Business limits that travel with the evidence</h2><ul class="limits-list" id="limits-list"></ul>
  <p class="note">Precision-sensitive source numbers are shown as exact text in disclosure. Original JSON numeric types and bytes are preserved in the full JSON download. CSV formula-like text is apostrophe-prefixed for spreadsheet safety; the JSON keeps the original text.</p>
  <p class="hash">Embedded full JSON SHA-256: <span id="snapshot-hash">__SNAPSHOT_HASH__</span></p>
</section>
</div>
</main>
<footer><p>A dated, offline operations review. No live refresh, recovery action, protection change, ticket or notification. Shared captures require separate privacy review; SIMULATED data is never live evidence.</p></footer>
<script id="snapshot-bytes" type="application/octet-stream">__SNAPSHOT_B64__</script>
<script id="jobs-csv-bytes" type="application/octet-stream">__JOBS_CSV_B64__</script>
<script id="coverage-csv-bytes" type="application/octet-stream">__COVERAGE_CSV_B64__</script>
<script>
"use strict";
(() => {
  const byId = id => document.getElementById(id);
  const text = value => value === null || value === undefined || value === "" ? "Unknown" : String(value);
  const node = (tag, value, className) => {
    const element = document.createElement(tag);
    if (value !== undefined) element.textContent = text(value);
    if (className) element.className = className;
    return element;
  };
  const cell = (label, ...children) => {
    const td = node("td"); td.dataset.label = label;
    for (const child of children) td.append(child);
    return td;
  };
  const pill = (value, kind) => node("span", value, "pill " + (["failed","warning","completed","in_progress","cancelled","unknown","complete","partial","denied","error","not_collected","Error","Warning","Attention","Unknown"].includes(kind) ? kind : "unknown"));
  function bytes(id) {
    const binary = atob(byId(id).textContent.trim());
    const result = new Uint8Array(binary.length);
    for (let i=0; i<binary.length; i++) result[i] = binary.charCodeAt(i);
    return result;
  }
  function displayModel(raw) {
    // Preserve unsafe numbers as exact display text; never use this model for export.
    let output = "", i = 0;
    while (i < raw.length) {
      if (raw[i] === '"') {
        const start = i++;
        while (i < raw.length) {
          if (raw[i] === "\\") { i += 2; continue; }
          if (raw[i++] === '"') break;
        }
        output += raw.slice(start,i);
      } else if (raw[i] === "-" || /[0-9]/.test(raw[i])) {
        const match = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(raw.slice(i));
        if (!match) throw new Error("Invalid embedded number.");
        const token = match[0], number = Number(token);
        const exact = Number.isFinite(number) && (/[.eE]/.test(token) ? String(number) === token : Number.isSafeInteger(number) && String(number) === token);
        output += exact ? token : JSON.stringify(token);
        i += token.length;
      } else { output += raw[i++]; }
    }
    return JSON.parse(output);
  }
  const disclosure = (label, value) => {
    const detail = node("details");
    detail.append(node("summary", label), node("pre", JSON.stringify(value, null, 2)));
    return detail;
  };
  const download = (id, filename, mime) => {
    const url = URL.createObjectURL(new Blob([bytes(id)], {type:mime}));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename;
    document.body.append(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  let snapshot, sourceMap, jobMap, itemMap, page = 0, printing = false;
  const pageSize = 40;
  function selectedVault(value) {
    const selected = byId("vault-filter").value;
    return !selected || String(value).toLowerCase() === selected.toLowerCase();
  }
  function matchesWindow(job) {
    const selected = byId("window-filter").value;
    if (selected === "all") return true;
    if (selected === "unknown") return job.window_membership === "unknown";
    if (selected === "requested") return job.window_membership === "in_requested_window";
    const start = Date.parse(job.start_time), reference = Date.parse(snapshot.reference_utc);
    if (!Number.isFinite(start)) return false;
    const boundary = selected === "last24" ? reference - 86400000 : Date.parse(snapshot.reference_utc.slice(0,10) + "T00:00:00Z");
    return start >= boundary && start < reference;
  }
  function matchingJobs() {
    const state = byId("state-filter").value, operation = byId("operation-filter").value;
    const item = byId("item-filter").value, query = byId("job-filter").value.trim().toLowerCase();
    return snapshot.jobs.filter(job => selectedVault(job.vault_id) && matchesWindow(job)
      && (state === "all" || [job.native_status,job.list_status,job.detail_status].some(value => JSON.stringify(value ?? null) === state))
      && (operation === "all" || JSON.stringify(job.operation ?? null) === operation)
      && (!item || (job.matched_item_id || "").toLowerCase() === item.toLowerCase())
      && (!query || [job.id,job.name,job.entity_name].some(value => typeof value === "string" && value.toLowerCase().includes(query))));
  }
  function rawRecord(reference) {
    if (!reference) return null;
    const body = sourceMap.get(reference.source_id).responses[reference.page].body;
    return reference.row === null ? body : body.value[reference.row];
  }
  function jobEvidence(job) {
    return {normalized:job, native_list:rawRecord(job.list_ref), native_job_details:rawRecord(job.detail_ref)};
  }
  function renderJobs() {
    const matches = matchingJobs();
    const pages = Math.max(1, Math.ceil(matches.length/pageSize));
    page = Math.min(page,pages-1);
    const visible = printing ? matches : matches.slice(page*pageSize,(page+1)*pageSize);
    const body = byId("jobs-body"); body.replaceChildren();
    for (const job of visible) {
      const row = node("tr"); row.dataset.recordKey = job.record_key;
      const identity = node("div");
      identity.append(node("strong",job.entity_name || job.name || "Unidentified source row"),node("small",job.id),node("small","Vault: " + job.vault_name));
      const status = node("div");
      status.append(pill(job.native_status,job.state_category),node("small","List: " + text(job.list_status)),node("small","Details: " + text(job.detail_status)));
      if (job.state_changed) status.append(node("small","State changed between reads; both retained."));
      const operation = node("div");
      operation.append(node("strong",job.operation),node("small","Group: " + job.operation_group),
        node("small","Management: " + text(job.backup_management_type)),node("small","Workload: " + text(job.workload_type)),
        node("small","Job type: " + text(job.job_type)),node("small","Source type: " + text(job.source_resource_type)));
      const dates = node("div");
      dates.append(node("time",job.start_time),node("small","End: " + text(job.end_time)),node("small","Native duration: " + text(job.duration_native)),
        node("small",job.window_membership));
      const evidence = node("div");
      evidence.append(node("small","Details read: " + job.details_collection_status),node("small","Item link: " + job.association_status),
        disclosure("Evidence / errors",jobEvidence(job)));
      row.append(cell("Job / entity",identity),cell("Native state",status),cell("Operation",operation),cell("UTC / duration",dates),cell("Evidence",evidence));
      body.append(row);
    }
    byId("jobs-empty").hidden = matches.length !== 0;
    byId("jobs-region").hidden = matches.length === 0;
    byId("previous").disabled = printing || page === 0;
    byId("next").disabled = printing || page+1 >= pages;
    const shown = visible.length;
    byId("page-note").textContent = matches.length ? (printing ? "All " + matches.length + " matching records printed." : "Records " + (page*pageSize+1) + "-" + (page*pageSize+shown) + " of " + matches.length + "; page " + (page+1) + " of " + pages + ".") : "0 matching records. Source coverage is separate.";
    byId("filter-summary").textContent = matches.length + " matching / " + snapshot.jobs.length + " received job records. Window: " + byId("window-filter").selectedOptions[0].textContent
      + "; vault: " + (byId("vault-filter").selectedOptions[0]?.textContent || "All") + "; state: " + byId("state-filter").selectedOptions[0].textContent
      + "; operation: " + byId("operation-filter").selectedOptions[0].textContent + "; item: " + (byId("item-filter").selectedOptions[0]?.textContent || "All")
      + "; text: " + (byId("job-filter").value || "none") + ". Full-file downloads ignore filters.";
  }
  function renderReview() {
    const rows = snapshot.human_review.filter(row => selectedVault(row.vault_id)
      && (row.kind !== "job" || matchesWindow(jobMap.get(row.record_key))));
    const container = byId("review-records"); container.replaceChildren();
    byId("review-note").textContent = rows.length + " candidates / blind spots in this vault/window selection. Not incident records.";
    if (!rows.length) container.append(node("p","No review candidates in this selection. This is not proof of successful protection or recovery.","empty"));
    for (const row of rows) {
      const article = node("article",undefined,"review-record");
      const title = node("div",undefined,"review-title");
      title.append(pill(row.severity,row.severity),node("strong",row.kind.replaceAll("_"," ")));
      article.append(title,node("p",row.reason),node("p",row.resource_id,"identity"));
      let evidence;
      if (row.kind === "job") evidence = jobEvidence(jobMap.get(row.record_key));
      else if (row.kind === "protected_item") {
        const item = itemMap.get(row.record_key); evidence = {normalized:item,native:rawRecord(item.source_ref)};
      } else if (row.kind === "source") evidence = sourceMap.get(row.source_id);
      else evidence = snapshot.history_coverage.find(item => item.vault_id === row.vault_id);
      article.append(disclosure("Review original evidence",evidence));
      container.append(article);
    }
  }
  function renderHistory() {
    const body = byId("history-body"); body.replaceChildren();
    for (const history of snapshot.history_coverage.filter(row => selectedVault(row.vault_id))) {
      const row = node("tr"), dates = node("div"), availability = node("div"), read = node("div");
      dates.append(node("div",history.requested_window.start_utc + " to " + history.requested_window.end_utc),
        node("small","Returned starts: " + text(history.observed_job_start_min) + " to " + text(history.observed_job_start_max)),
        node("small","Returned span is not continuous coverage."));
      availability.append(pill(history.history_status,"unknown"));
      if (!history.verified_available_intervals.length) availability.append(node("div","No verified availability interval."));
      for (const interval of history.verified_available_intervals) availability.append(node("small","Verified: " + interval.start_utc + " to " + interval.end_utc));
      for (const interval of history.unverified_or_unknown_intervals) availability.append(node("small","Unknown/unverified: " + interval.start_utc + " to " + interval.end_utc));
      read.append(pill(history.query_status,history.query_status),node("small","Pagination complete: " + history.pagination_complete),disclosure("History receipt",history));
      row.append(cell("Vault",node("strong",history.vault_id.split("/").at(-1)),node("small",history.vault_id)),
        cell("UTC windows",dates),cell("Availability",availability),cell("Read evidence",read));
      body.append(row);
    }
  }
  function renderItems() {
    const items = snapshot.protected_items.filter(item => selectedVault(item.vault_id));
    const body = byId("items-body"); body.replaceChildren();
    for (const item of items) {
      const row = node("tr"), identity = node("div"), state = node("div"), dates = node("div"), association = node("div");
      identity.append(node("strong",item.name),node("small",item.id),node("small","Source: " + text(item.source_resource_id)));
      state.append(node("div","State: " + text(item.protection_state)),node("small","Protection status: " + text(item.protection_status)),
        node("small","Last backup status: " + text(item.last_backup_status)),node("small","Policy: " + text(item.policy_id)));
      dates.append(node("div","Last backup: " + text(item.last_backup_time)),node("small","Latest recovery point: " + text(item.last_recovery_point)));
      association.append(node("div",item.matched_backup_job_records + " exact-linked Backup records in requested window"),
        node("small","Expected / missed jobs: Unknown"),node("small","Association: " + item.job_association_status),
        disclosure("Item evidence",{normalized:item,native:rawRecord(item.source_ref)}));
      row.append(cell("Item identity",identity),cell("Native metadata",state),cell("Native dates",dates),cell("Association",association)); body.append(row);
    }
    byId("items-empty").hidden = items.length !== 0;
    byId("items-region").hidden = items.length === 0;
  }
  function renderSources() {
    const rows = snapshot.sources.filter(source => source.kind === "subscription" || selectedVault(source.scope_id));
    const body = byId("sources-body"); body.replaceChildren();
    const errors = rows.filter(source => source.status !== "complete").length;
    byId("source-note").textContent = rows.length + " source receipts; " + errors + " incomplete/denied/not-collected reads. Complete reads may legitimately return zero rows.";
    for (const source of rows) {
      const row = node("tr"), identity = node("div"), status = node("div"), counts = node("div"), receipt = node("div");
      identity.append(node("strong",source.kind),node("small",source.source_id),node("small",source.scope_id));
      status.append(pill(source.status,source.status),node("small","Pagination complete: " + source.pagination_complete));
      counts.append(node("div",source.responses.length + " received pages / " + source.records_received + " source records"),
        node("small","Latest received UTC: " + text(source.responses.at(-1)?.received_utc)));
      receipt.append(node("small",source.errors.length ? source.errors.map(error => error.code + ": " + error.message).join("\n") : "No read errors recorded."),
        disclosure("Full source receipt",source));
      row.append(cell("Source / scope",identity),cell("Read status",status),cell("Pages / rows",counts),cell("Original receipt",receipt)); body.append(row);
    }
  }
  function renderAll() { renderJobs(); renderReview(); renderHistory(); renderItems(); renderSources(); }
  function options(select, values, allLabel) {
    select.replaceChildren();
    const all = node("option",allLabel); all.value = "all"; select.append(all);
    const unique = [...new Map(values.map(value => [JSON.stringify(value ?? null),value ?? null])).entries()];
    unique.sort((a,b) => text(a[1]).localeCompare(text(b[1])));
    for (const [value,label] of unique) { const option = node("option",label); option.value = value; select.append(option); }
  }
  function reset() {
    byId("vault-filter").value = "";
    byId("window-filter").value = "requested";
    byId("state-filter").value = "all";
    byId("operation-filter").value = "all";
    byId("item-filter").value = "";
    byId("job-filter").value = "";
    page = 0; renderAll();
  }
  try {
    const raw = new TextDecoder("utf-8",{fatal:true}).decode(bytes("snapshot-bytes"));
    snapshot = displayModel(raw);
    if (snapshot.schema_version !== "azure-backup-operations-v1") throw new Error("Unsupported evidence schema.");
    sourceMap = new Map(snapshot.sources.map(source => [source.source_id,source]));
    jobMap = new Map(snapshot.jobs.map(job => [job.record_key,job]));
    itemMap = new Map(snapshot.protected_items.map(item => [item.record_key,item]));
    byId("reference").textContent = "Reference UTC " + snapshot.reference_utc;
    const provenanceLabels = {
      SIMULATED:"SIMULATED / NOT LIVE EVIDENCE",
      LIVE:"LIVE SOURCE / DATED SNAPSHOT",
      RECORDED_REPLAY:"RECORDED REPLAY / NOT A FRESH COLLECTION"
    };
    if (!Object.hasOwn(provenanceLabels,snapshot.provenance)) throw new Error("Unknown evidence provenance.");
    byId("provenance").textContent = provenanceLabels[snapshot.provenance];
    if (snapshot.provenance === "RECORDED_REPLAY") byId("finished-label").textContent="Recorded probe finished (UTC), not replay time";
    byId("requested-start").textContent = snapshot.requested_window.start_utc;
    byId("requested-end").textContent = snapshot.requested_window.end_utc;
    byId("vault-count").textContent = snapshot.scope.approved_vault_ids.length + " (fixed allowlist)";
    byId("finished").textContent = snapshot.collection_finished_utc;
    byId("backup-count").textContent = snapshot.summary.backup_job_records_in_window;
    byId("other-count").textContent = snapshot.summary.other_operation_records_in_window;
    byId("item-count").textContent = snapshot.summary.observed_protected_item_records;
    byId("scope-text").textContent = JSON.stringify({scope:snapshot.scope,limits:snapshot.limits,window:snapshot.requested_window},null,2);
    byId("coverage-notice").textContent = snapshot.summary.history_unverified_vaults + " vault(s) have unverified requested history; "
      + snapshot.summary.source_issues + " source read(s) are incomplete/denied/not collected. Expected protection and schedules are Unknown. Read completion does not prove historical availability.";
    byId("retained-note").textContent = snapshot.summary.unknown_time_records + " record(s) have Unknown start time; "
      + snapshot.summary.outside_window_records + " are outside the requested interval. They remain in all exports and the All received source rows view.";
    const vaultSelect = byId("vault-filter"), allVaults = node("option","All approved vaults"); allVaults.value = ""; vaultSelect.append(allVaults);
    for (const id of snapshot.scope.approved_vault_ids) { const option = node("option",id.split("/").at(-1) + " | " + id); option.value = id; vaultSelect.append(option); }
    options(byId("state-filter"),snapshot.jobs.flatMap(job => [job.native_status,job.list_status,job.detail_status]),"All native states");
    options(byId("operation-filter"),snapshot.jobs.map(job => job.operation),"All operations");
    const itemSelect = byId("item-filter"), allItems = node("option","All / no exact item link"); allItems.value = ""; itemSelect.append(allItems);
    for (const item of snapshot.protected_items) { if (typeof item.id === "string") { const option = node("option",text(item.name) + " | " + item.id); option.value = item.id; itemSelect.append(option); } }
    for (const message of snapshot.business_limits) byId("limits-list").append(node("li",message));
    for (const id of ["vault-filter","window-filter","state-filter","operation-filter","item-filter"]) byId(id).addEventListener("change",() => { page=0; renderAll(); });
    byId("job-filter").addEventListener("input",() => { page=0; renderJobs(); });
    byId("reset").addEventListener("click",reset);
    byId("today").addEventListener("click",() => { byId("window-filter").value="last24"; page=0; renderAll(); byId("window-filter").focus(); });
    byId("previous").addEventListener("click",() => { if(page>0) page--; renderJobs(); });
    byId("next").addEventListener("click",() => { page++; renderJobs(); });
    const stamp = snapshot.reference_utc.replaceAll(":","").replaceAll("-","");
    byId("export-json").addEventListener("click",() => download("snapshot-bytes","azure-backup-" + stamp + ".json","application/json"));
    byId("export-jobs").addEventListener("click",() => download("jobs-csv-bytes","azure-backup-" + stamp + "-jobs.csv","text/csv"));
    byId("export-coverage").addEventListener("click",() => download("coverage-csv-bytes","azure-backup-" + stamp + "-coverage.csv","text/csv"));
    let openBeforePrint = [];
    window.addEventListener("beforeprint",() => {
      printing=true; renderJobs();
      openBeforePrint = [...document.querySelectorAll("details[open]")];
      for (const details of document.querySelectorAll("details")) details.open=true;
    });
    window.addEventListener("afterprint",() => {
      for (const details of document.querySelectorAll("details")) if (!openBeforePrint.includes(details)) details.open=false;
      printing=false; renderJobs();
    });
    byId("print").addEventListener("click",() => window.print());
    renderAll();
    for (const id of ["export-json","export-jobs","export-coverage","print"]) byId(id).disabled=false;
    byId("opening").hidden=true; byId("report").hidden=false;
  } catch (error) {
    byId("opening").hidden=true; byId("report").hidden=true; byId("fatal").hidden=false;
    byId("fatal-message").textContent="The embedded snapshot could not be decoded/rendered (" + (error instanceof Error ? error.message : "unknown error") + ").";
  }
})();
</script>
</body>
</html>
"""


def render_html(snapshot, document, jobs_csv, coverage_csv, branding):
    logo = (
        '<img src="' + html.escape(branding["logo"], quote=True) + '" alt="' + html.escape(branding["alt"], quote=True) + '">'
        if branding["logo"] else '<span class="placeholder">' + html.escape(branding["name"]) + '<small>Customer logo</small></span>'
    )
    replacements = {
        "__LOGO__": logo, "__CLIENT__": html.escape(branding["name"]),
        "__SNAPSHOT_B64__": base64.b64encode(document).decode("ascii"),
        "__JOBS_CSV_B64__": base64.b64encode(jobs_csv).decode("ascii"),
        "__COVERAGE_CSV_B64__": base64.b64encode(coverage_csv).decode("ascii"),
        "__SNAPSHOT_HASH__": hashlib.sha256(document).hexdigest(),
    }
    rendered = HTML_TEMPLATE
    for marker, value in replacements.items():
        if rendered.count(marker) != 1:
            raise EvidenceError("template_contract", "Standalone report template has an invalid placeholder count.", "renderer")
        rendered = rendered.replace(marker, value, 1)
    return rendered.encode("utf-8")


def main(period: str = "last_14d") -> dict:
    """Collect only existing, explicitly allowed Recovery Services evidence."""
    identity = None
    try:
        reference = utc_now()
        requested_window(period, reference)
        branding = validate_branding()
        config = validate_config()
        artifact_directory()
        identity = Identity(config)
        snapshot = collect_snapshot(HttpReader(identity, config), config, period, reference)
        return write_report(snapshot, branding)
    except EvidenceError as exc:
        return ensure_response({"status": "error", "error": exc.public(), "artifacts_created": None if exc.artifacts_may_remain else False,
                                "artifacts_may_remain": exc.artifacts_may_remain})
    finally:
        if identity is not None:
            identity.close()
