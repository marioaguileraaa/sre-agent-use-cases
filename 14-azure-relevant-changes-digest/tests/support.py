"""Shared offline test support for case 14 (no network, no Azure SDK)."""

import base64
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "generate-azure-change-digest.py"
SUB = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
CLIENT_ID = "12345678-1234-4abc-8def-123456789abc"
TENANT = "11111111-1111-4111-8111-111111111111"
NOW = datetime(2026, 11, 6, 18, 0, 0, tzinfo=timezone.utc)
HUMAN = "alice@contoso.com"
AKS_APP = "be1a5d97-013c-4105-b240-4a6428fdd4c8"


def load_tool(configure=True):
    spec = importlib.util.spec_from_file_location("change_digest_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if configure:
        module.MANAGED_IDENTITY_CLIENT_ID = CLIENT_ID
        module.SUBSCRIPTION_IDS = [SUB]
    return module


def make_jwt(claims):
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode("utf-8")).decode("ascii").rstrip("=")
    return part({"alg": "RS256", "typ": "JWT"}) + "." + part(claims) + ".signature"


def resource_id(rtype, name, rg="rg-app"):
    return f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/{rtype}/{name}"


_counter = [0]


def row(rtype, name, change_type="Update", changes=None, by=HUMAN, by_type="User", client="CLI", op=None, rg="rg-app",
        ts="2026-11-06T10:39:24Z", corr=None):
    _counter[0] += 1
    rid = resource_id(rtype, name, rg)
    bag = {path: {"previousValue": prev or None, "newValue": new or None} for path, (prev, new) in (changes or {}).items()}
    return {
        "id": f"{rid}/providers/Microsoft.Resources/changes/08584_{_counter[0]:08d}", "ts": ts, "subscriptionId": SUB,
        "resourceGroup": rg, "targetResourceId": rid, "targetResourceType": rtype, "changeType": change_type,
        "changedBy": by, "changedByType": by_type, "clientType": client, "operation": op or (rtype + "/write"),
        "correlationId": corr or f"{_counter[0]:08d}-0000-4000-8000-000000000000", "changesCount": len(bag), "changes": bag,
    }


def containers(managed=(), prod=()):
    rows = [{"id": f"/subscriptions/{SUB}", "type": "microsoft.resources/subscriptions", "name": "Contoso Production",
             "subscriptionId": SUB, "managedBy": "", "tags": {}}]
    for rg in set(managed) | set(prod) | {"rg-app"}:
        rows.append({"id": f"/subscriptions/{SUB}/resourceGroups/{rg}", "type": "microsoft.resources/subscriptions/resourcegroups",
                     "name": rg, "subscriptionId": SUB, "managedBy": "/subscriptions/x/aks" if rg in managed else "",
                     "tags": {"Environment": "Prod"} if rg in prod else {}})
    return rows


def raw_for(candidates, managed=(), prod=(), baseline=(), nsg_rules=None, role_rows=(), gaps=(), noise_types=(), noise_paths=()):
    return {"sources": [], "role_names": {}, "nsg_rules": nsg_rules or {}, "resource_tags": {}, "gaps": list(gaps), "failed_gaps": [],
            "ra_callers": {}, "baseline": list(baseline), "subscription_names": {SUB: "Contoso Production"},
            "containers": containers(managed, prod), "candidates": list(candidates), "container_changes": [],
            "noise_types": list(noise_types), "noise_paths": list(noise_paths), "role_assignment_rows": list(role_rows)}


def params(module, period="last_24h", **kwargs):
    return module.validate_parameters(period=period, now=NOW, **kwargs)


def classify(module, candidate, managed=(), prod=(), expected=None, nsg_rules=None):
    module.EXPECTED_AUTOMATION = expected or {}
    config = module.validate_config()
    ctx = module.build_context(raw_for([candidate], managed, prod, nsg_rules=nsg_rules), config)
    change = module.normalize_change(candidate, "resourcechanges")
    return module.classify_change(change, ctx)


def analyze(module, candidates, period="last_24h", **raw_kwargs):
    config = module.validate_config()
    p = params(module, period)
    raw = raw_for(candidates, **raw_kwargs)
    return module.analyze(raw, config, p), raw, config, p


def snapshot(module, candidates, period="last_24h", min_level="medium", **raw_kwargs):
    config = module.validate_config()
    p = module.validate_parameters(period=period, min_level=min_level, now=NOW)
    raw = raw_for(candidates, **raw_kwargs)
    analysis = module.analyze(raw, config, p)
    stats = {"requests": 7, "throttled": 0, "seconds": 3.2, "identity": {"arm": "verified sidecar placeholder token"}}
    return module.build_snapshot(analysis, raw, config, p, stats), p


class FakeReader:
    """Replays canned JSON payloads in order; records requests."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []
        self.requests = 0
        self.throttled = 0

    def request(self, method, url, source, body=None):
        self.calls.append((method, url, body))
        if not self.payloads:
            raise AssertionError("Unexpected extra request")
        value = self.payloads.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def remaining(self):
        return 60


def at(minutes):
    return (NOW - timedelta(hours=8) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
