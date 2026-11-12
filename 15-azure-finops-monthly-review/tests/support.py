"""Shared helpers for the offline unit tests (no network: every HTTP call goes to a fake opener)."""
import email.message
import importlib.util
import io
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "generate-azure-finops-review.py"
SUB_A = "11111111-1111-1111-1111-111111111111"
SUB_B = "22222222-2222-2222-2222-222222222222"
CLIENT = "33333333-3333-3333-3333-333333333333"


def load_tool(name="finops_review_under_test"):
    spec = importlib.util.spec_from_file_location(name, TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.time.sleep = lambda seconds: None
    return module


def configure(module, subs=(SUB_A,), mg=""):
    module.MANAGED_IDENTITY_CLIENT_ID = CLIENT
    module.SUBSCRIPTION_IDS = list(subs)
    module.MANAGEMENT_GROUP_ID = mg
    return module.validate_config()


def headers(pairs=None):
    message = email.message.Message()
    for key, value in (pairs or {}).items():
        message[key] = value
    return message


class Response:
    def __init__(self, payload, status=200):
        self.status, self.headers = status, headers({"content-type": "application/json"})
        self._data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def read(self, size=-1):
        return self._data if size < 0 else self._data[:size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(url, code, hdrs=None, body=b'{"error":{"message":"denied"}}'):
    return HTTPError(url, code, "error", headers(hdrs), io.BytesIO(body))


class ScriptedOpener:
    """Returns (or raises) scripted results in order; records method, path and body of every request."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def open(self, request, timeout=None):
        self.calls.append((request.get_method(), request.full_url, json.loads(request.data) if request.data else None))
        if not self.script:
            raise AssertionError("unexpected extra request: " + request.full_url)
        item = self.script.pop(0)
        if callable(item):
            item = item(request)
        if isinstance(item, Exception):
            raise item
        return item


def now():
    return datetime(2026, 11, 3, 7, 0, 0, tzinfo=timezone.utc)


def stub_identity_module():
    package, module = types.ModuleType("azure"), types.ModuleType("azure.identity")

    class AccessToken:
        token, expires_on = "header.eyJ9.sig", 4102444800

    class ManagedIdentityCredential:
        def __init__(self, client_id=None, **_):
            self.client_id = client_id

        def get_token(self, scope, **_):
            return AccessToken()

        def close(self):
            pass

    module.ManagedIdentityCredential = ManagedIdentityCredential
    package.identity = module
    sys.modules["azure"], sys.modules["azure.identity"] = package, module
