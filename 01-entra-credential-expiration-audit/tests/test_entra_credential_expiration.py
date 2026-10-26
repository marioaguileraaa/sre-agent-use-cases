"""Offline unit tests for Use Case 01 (Microsoft Entra credential expiration audit).

Uses standard-library unittest and unittest.mock only. Never performs live Microsoft
Graph requests, token acquisitions, or unmocked writes to /mnt/data.
"""

from __future__ import annotations

import ast
import base64
import builtins
import datetime as dt
import importlib.util
import inspect
import io
import os
import re
import runpy
import socket
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

CASE_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = CASE_DIR / "generate-entra-credential-expiration.py"
README_PATH = CASE_DIR / "README.md"
SKILL_PATH = CASE_DIR / "SKILL.md"
PROMPTS_PATH = CASE_DIR / "subagent-instructions-and-prompts.md"

TEST_CLIENT_ID = "00000000-0000-4000-8000-000000000001"
FIXED_NOW_UTC = dt.datetime(2026, 10, 15, 9, 30, 0, tzinfo=dt.timezone.utc)


def load_raw_module(module_name: str = "entra_credential_expiration_raw") -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_configured_module(client_id: str = TEST_CLIENT_ID) -> types.ModuleType:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    target = 'MANAGED_IDENTITY_CLIENT_ID = "<YOUR_AGENT_CLIENT_ID>"'
    if target not in source:
        raise AssertionError("Expected MANAGED_IDENTITY_CLIENT_ID placeholder in script")
    patched_source = source.replace(
        target,
        f"MANAGED_IDENTITY_CLIENT_ID = {client_id!r}",
        1,
    )
    module = types.ModuleType("entra_credential_expiration_configured")
    module.__file__ = str(SCRIPT_PATH)
    code = compile(patched_source, str(SCRIPT_PATH), "exec")
    exec(code, module.__dict__)
    return module


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: object = None) -> None:
        self.status_code = status_code
        self._payload = payload

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FixedDateTime(dt.datetime):
    @classmethod
    def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
        if tz is None:
            return FIXED_NOW_UTC.replace(tzinfo=None)
        return FIXED_NOW_UTC.astimezone(tz)


class MemoryFile(io.StringIO):
    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        pass


def make_mock_dependencies(
    responses_by_url: dict[str, FakeResponse | list[FakeResponse]] | None = None,
    token_Error: Exception | None = None,
    token_value: str = "mock-graph-token",
) -> tuple[dict[str, types.ModuleType], MagicMock, MagicMock, list[tuple[str, int | None]]]:
    cred_instance = MagicMock()
    if token_Error is not None:
        cred_instance.get_token.side_effect = token_Error
    else:
        token_obj = MagicMock()
        token_obj.token = token_value
        cred_instance.get_token.return_value = token_obj

    cred_cls = MagicMock(return_value=cred_instance)
    azure_mod = types.ModuleType("azure")
    azure_identity_mod = types.ModuleType("azure.identity")
    azure_identity_mod.ManagedIdentityCredential = cred_cls
    azure_mod.identity = azure_identity_mod

    get_calls: list[tuple[str, int | None]] = []
    url_queues: dict[str, list[FakeResponse]] = {}
    for url, item in (responses_by_url or {}).items():
        url_queues[url] = list(item) if isinstance(item, list) else [item]

    session_instance = MagicMock()
    session_instance.headers = {}

    def side_effect_get(url: str, timeout: int | None = None) -> FakeResponse:
        get_calls.append((url, timeout))
        if url not in url_queues or not url_queues[url]:
            raise AssertionError(f"Unexpected Graph URL requested: {url}")
        return url_queues[url].pop(0)

    session_instance.get.side_effect = side_effect_get
    requests_mod = types.ModuleType("requests")
    requests_mod.Session = MagicMock(return_value=session_instance)

    modules = {
        "azure": azure_mod,
        "azure.identity": azure_identity_mod,
        "requests": requests_mod,
    }
    return modules, cred_cls, session_instance, get_calls


class ModuleContractAndSafetyTests(unittest.TestCase):
    def test_module_load_and_main_guard_have_zero_side_effects_and_zero_stdout(self) -> None:
        raw_text = SCRIPT_PATH.read_text(encoding="utf-8")
        lines = raw_text.splitlines()
        self.assertGreater(len(lines), 50)
        for idx, line in enumerate(lines, start=1):
            self.assertLess(
                len(line),
                10_000,
                f"Line {idx} exceeds 10,000 characters ({len(line)} chars)",
            )

        stdout_buf = io.StringIO()
        with (
            patch.object(socket, "create_connection", side_effect=AssertionError("Network call on import")),
            patch.object(os, "makedirs", side_effect=AssertionError("os.makedirs called on import")),
            patch("sys.stdout", stdout_buf),
        ):
            mod = load_raw_module()
            runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

        self.assertEqual(stdout_buf.getvalue(), "")
        self.assertTrue(hasattr(mod, "main"))
        self.assertTrue(callable(mod.main))
        sig = inspect.signature(mod.main)
        self.assertEqual(len(sig.parameters), 0)
        self.assertEqual(sig.return_annotation, dict)

    def test_unreplaced_or_empty_placeholder_fails_before_credential_or_network(self) -> None:
        for bad_client_id in ("<YOUR_AGENT_CLIENT_ID>", "<PLACEHOLDER>", ""):
            with self.subTest(client_id=bad_client_id):
                mod = (
                    load_raw_module()
                    if bad_client_id == "<YOUR_AGENT_CLIENT_ID>"
                    else load_configured_module(bad_client_id)
                )
                modules, cred_cls, session_instance, get_calls = make_mock_dependencies()
                with (
                    patch.dict(sys.modules, modules),
                    patch.object(os, "makedirs", side_effect=AssertionError("Must not create dirs")),
                ):
                    result = mod.main()
                self.assertEqual(result["coverage"], "partial")
                self.assertIn("Configuration required:", result["error"])
                cred_cls.assert_not_called()
                session_instance.get.assert_not_called()
                self.assertEqual(get_calls, [])

    def test_token_acquisition_failure_returns_partial_without_calling_graph(self) -> None:
        mod = load_configured_module(TEST_CLIENT_ID)
        modules, cred_cls, session_instance, get_calls = make_mock_dependencies(
            token_Error=RuntimeError("UAMI not assigned to host")
        )
        with (
            patch.dict(sys.modules, modules),
            patch.object(os, "makedirs", side_effect=AssertionError("Must not write report on token error")),
        ):
            result = mod.main()

        cred_cls.assert_called_once_with(client_id=TEST_CLIENT_ID)
        self.assertEqual(result["coverage"], "partial")
        self.assertIn("Failed to acquire Microsoft Graph token:", result["error"])
        self.assertIn("UAMI not assigned to host", result["error"])
        session_instance.get.assert_not_called()
        self.assertEqual(get_calls, [])


class GraphHttpAndPaginationTests(unittest.TestCase):
    APPS_URL = (
        "https://graph.microsoft.com/v1.0/applications"
        "?$select=displayName,appId,id,passwordCredentials,keyCredentials"
        "&$top=999"
    )
    SPS_URL = (
        "https://graph.microsoft.com/v1.0/servicePrincipals"
        "?$select=displayName,appId,id,servicePrincipalType,"
        "passwordCredentials,keyCredentials"
        "&$top=999"
    )

    def test_http_401_and_403_return_authorization_failed_and_write_nothing(self) -> None:
        mod = load_configured_module(TEST_CLIENT_ID)
        for status_code in (401, 403):
            with self.subTest(status_code=status_code):
                modules, _, _, _ = make_mock_dependencies(
                    responses_by_url={self.APPS_URL: FakeResponse(status_code=status_code, payload={})}
                )
                with (
                    patch.dict(sys.modules, modules),
                    patch.object(os, "makedirs", side_effect=AssertionError("Must not write report")),
                ):
                    result = mod.main()
                self.assertEqual(
                    result,
                    {
                        "error": f"Microsoft Graph authorization failed: HTTP {status_code}.",
                        "coverage": "partial",
                    },
                )

    def test_http_429_and_500_return_request_failed_and_write_nothing(self) -> None:
        mod = load_configured_module(TEST_CLIENT_ID)
        for status_code in (429, 500, 503):
            with self.subTest(status_code=status_code):
                modules, _, _, _ = make_mock_dependencies(
                    responses_by_url={self.APPS_URL: FakeResponse(status_code=status_code, payload={})}
                )
                with (
                    patch.dict(sys.modules, modules),
                    patch.object(os, "makedirs", side_effect=AssertionError("Must not write report")),
                ):
                    result = mod.main()
                self.assertEqual(
                    result,
                    {
                        "error": f"Microsoft Graph request failed: HTTP {status_code}.",
                        "coverage": "partial",
                    },
                )

    def test_malformed_graph_payload_returns_unexpected_response_format(self) -> None:
        mod = load_configured_module(TEST_CLIENT_ID)
        for bad_payload in (["not-a-dict"], {"error": "missing value key"}, None, "raw-string"):
            with self.subTest(payload=bad_payload):
                modules, _, _, _ = make_mock_dependencies(
                    responses_by_url={self.APPS_URL: FakeResponse(status_code=200, payload=bad_payload)}
                )
                with (
                    patch.dict(sys.modules, modules),
                    patch.object(os, "makedirs", side_effect=AssertionError("Must not write report")),
                ):
                    result = mod.main()
                self.assertEqual(
                    result,
                    {
                        "error": "Unexpected response format returned by Microsoft Graph.",
                        "coverage": "partial",
                    },
                )

    def test_mid_pagination_failure_aborts_without_writing_incomplete_report(self) -> None:
        mod = load_configured_module(TEST_CLIENT_ID)
        apps_page_2 = "https://graph.microsoft.com/v1.0/applications?$skiptoken=page2"
        modules, _, _, get_calls = make_mock_dependencies(
            responses_by_url={
                self.APPS_URL: FakeResponse(
                    status_code=200,
                    payload={
                        "value": [{"id": "app-1", "appId": "a1", "displayName": "App 1"}],
                        "@odata.nextLink": apps_page_2,
                    },
                ),
                apps_page_2: FakeResponse(status_code=502, payload={}),
            }
        )
        with (
            patch.dict(sys.modules, modules),
            patch.object(os, "makedirs", side_effect=AssertionError("Must not write partial report")),
        ):
            result = mod.main()

        self.assertEqual(
            result,
            {
                "error": "Microsoft Graph request failed: HTTP 502.",
                "coverage": "partial",
            },
        )
        self.assertEqual([call[0] for call in get_calls], [self.APPS_URL, apps_page_2])

    def test_multi_page_pagination_succeeds_across_applications_and_service_principals(self) -> None:
        mod = load_configured_module(TEST_CLIENT_ID)
        apps_page_2 = "https://graph.microsoft.com/v1.0/applications?$skiptoken=apps2"
        sps_page_2 = "https://graph.microsoft.com/v1.0/servicePrincipals?$skiptoken=sps2"
        written_files: dict[str, MemoryFile] = {}

        def fake_open(path: str, mode: str = "r", encoding: str | None = None) -> MemoryFile:
            buf = MemoryFile()
            written_files[str(path)] = buf
            return buf

        modules, _, _, get_calls = make_mock_dependencies(
            responses_by_url={
                self.APPS_URL: FakeResponse(
                    200,
                    {
                        "value": [{"id": "app-1", "appId": "app-id-1", "displayName": "App One"}],
                        "@odata.nextLink": apps_page_2,
                    },
                ),
                apps_page_2: FakeResponse(
                    200,
                    {
                        "value": [{"id": "app-2", "appId": "app-id-2", "displayName": "App Two"}],
                    },
                ),
                self.SPS_URL: FakeResponse(
                    200,
                    {
                        "value": [
                            {
                                "id": "sp-mi",
                                "appId": "mi-app",
                                "displayName": "id-sre-agent",
                                "servicePrincipalType": "ManagedIdentity",
                            }
                        ],
                        "@odata.nextLink": sps_page_2,
                    },
                ),
                sps_page_2: FakeResponse(
                    200,
                    {
                        "value": [
                            {
                                "id": "sp-app",
                                "appId": "sp-app-id",
                                "displayName": "Enterprise SP",
                                "servicePrincipalType": "Application",
                            }
                        ],
                    },
                ),
            }
        )
        with (
            patch.dict(sys.modules, modules),
            patch.object(dt, "datetime", FixedDateTime),
            patch.object(os, "makedirs") as makedirs_mock,
            patch.object(builtins, "open", side_effect=fake_open),
        ):
            result = mod.main()

        makedirs_mock.assert_called_once_with("/mnt/data", exist_ok=True)
        self.assertEqual(len(get_calls), 4)
        self.assertTrue( all(timeout == 60 for _, timeout in get_calls) )
        self.assertEqual(result["application_count"], 2)
        self.assertEqual(result["service_principal_count"], 1)
        self.assertEqual(result["managed_identity_excluded_count"], 1)
        self.assertEqual(result["coverage"]["status"], "complete")
        self.assertTrue(result["coverage"]["pagination_completed"])
        self.assertEqual(result["report_path"], "/mnt/data/entra-credential-expiration-audit-2026-10-15.html")
        self.assertIn(result["report_path"], written_files)


class ClassificationScopeAndHtmlTests(unittest.TestCase):
    APPS_URL = GraphHttpAndPaginationTests.APPS_URL
    SPS_URL = GraphHttpAndPaginationTests.SPS_URL

    def _run_audit(
        self,
        applications: list[dict[str, object]],
        service_principals: list[dict[str, object]],
    ) -> tuple[dict[str, object], str]:
        mod = load_configured_module(TEST_CLIENT_ID)
        written_files: dict[str, MemoryFile] = {}

        def fake_open(path: str, mode: str = "r", encoding: str | None = None) -> MemoryFile:
            buf = MemoryFile()
            written_files[str(path)] = buf
            return buf

        modules, _, _, _ = make_mock_dependencies(
            responses_by_url={
                self.APPS_URL: FakeResponse(200, {"value": applications}),
                self.SPS_URL: FakeResponse(200, {"value": service_principals}),
            }
        )
        with (
            patch.dict(sys.modules, modules),
            patch.object(dt, "datetime", FixedDateTime),
            patch.object(os, "makedirs"),
            patch.object(builtins, "open", side_effect=fake_open),
        ):
            result = mod.main()
        html_out = written_files[result["report_path"]].getvalue()
        return result, html_out

    def test_calendar_day_classification_boundaries_and_managed_identity_exclusion(self) -> None:
        # Reference UTC date is 2026-10-15 (09:30:00Z)
        applications = [
            {
                "id": "app-obj-1",
                "appId": "11111111-1111-1111-1111-111111111111",
                "displayName": "Portal <script>alert(1)</script> App",
                "passwordCredentials": [
                    {"displayName": "past-expired", "endDateTime": "2026-10-14T23:59:59Z"},  # -1 -> EXPIRED
                    {"displayName": "same-day-later-hour", "endDateTime": "2026-10-15T23:59:59Z"},  # 0 -> EXPIRED
                    {"displayName": "crit-low", "endDateTime": "2026-10-16T00:00:00Z"},  # 1 -> CRITICAL
                    {"displayName": "crit-high", "endDateTime": "2026-10-22T12:00:00Z"},  # 7 -> CRITICAL
                    {"displayName": "soon-low", "endDateTime": "2026-10-23T00:00:00Z"},  # 8 -> EXPIRING SOON
                    {"displayName": "soon-high", "endDateTime": "2026-11-14T00:00:00Z"},  # 30 -> EXPIRING SOON
                ],
                "keyCredentials": [
                    {"displayName": "expiring-low", "endDateTime": "2026-11-15T00:00:00Z"},  # 31 -> EXPIRING
                    {"displayName": "expiring-high", "endDateTime": "2027-01-13T00:00:00Z"},  # 90 -> EXPIRING
                    {"displayName": "valid-low", "endDateTime": "2027-01-14T00:00:00Z"},  # 91 -> Valid
                    {"displayName": "missing-date", "endDateTime": None},  # None -> UNKNOWN
                    {"displayName": "bad-date", "endDateTime": "not-a-timestamp"},  # invalid -> UNKNOWN
                ],
            }
        ]
        service_principals = [
            {
                "id": "sp-mi-1",
                "appId": "22222222-2222-2222-2222-222222222222",
                "displayName": "Managed Identity SP",
                "servicePrincipalType": "ManagedIdentity",
                "keyCredentials": [
                    {"displayName": "mi-cert-must-be-excluded", "endDateTime": "2026-10-01T00:00:00Z"}
                ],
            },
            {
                "id": "sp-regular-1",
                "appId": "33333333-3333-3333-3333-333333333333",
                "displayName": "Regular Service Principal",
                "servicePrincipalType": "Application",
                "passwordCredentials": [
                    {"displayName": "sp-secret-<script>", "endDateTime": "2026-10-20T00:00:00Z"},  # 5 -> CRITICAL
                ],
                "keyCredentials": [],
            },
        ]

        result, html_out = self._run_audit(applications, service_principals)
        self.assertEqual(result["application_count"], 1)
        self.assertEqual(result["service_principal_count"], 1)
        self.assertEqual(result["managed_identity_excluded_count"], 1)
        self.assertEqual(
            result["counts_by_status"],
            {
                "EXPIRED": 2,
                "CRITICAL": 3,
                "EXPIRING SOON": 2,
                "EXPIRING": 2,
                "Valid": 1,
                "UNKNOWN": 2,
            },
        )
        self.assertEqual(result["coverage"]["credential_rows"], 12)
        self.assertEqual(result["coverage"]["reference_utc"], "2026-10-15T09:30:00Z")

        # Urgent signal when EXPIRED + CRITICAL > 0
        self.assertIn("signal--urgent", html_out)
        self.assertIn("Action required", html_out)
        self.assertIn("5 credential(s) need owner review now.", html_out)

        # ManagedIdentity credentials excluded
        self.assertNotIn("mi-cert-must-be-excluded", html_out)

        # HTML escaping & interactive controls verified
        self.assertNotIn("<script>alert(1)</script>", html_out)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html_out)
        self.assertIn("sp-secret-&lt;script&gt;", html_out)
        for control_id in ("f_name", "f_min", "f_max", "f_status", "f_object"):
            self.assertIn(f'id="{control_id}"', html_out)
        self.assertIn("<option>UNKNOWN</option>", html_out)
        self.assertIn("exportCsv()", html_out)
        self.assertIn("\\ufeff", html_out)
        self.assertIn("\\r\\n", html_out)

        # No external stylesheets, scripts, or fonts
        self.assertNotRegex(html_out, r'<(?:script|link|img)\b[^>]+(?:src|href)="https?://')

    def test_clear_signal_when_no_expired_or_critical_credentials_exist(self) -> None:
        applications = [
            {
                "id": "app-clear",
                "appId": "44444444-4444-4444-4444-444444444444",
                "displayName": "Healthy App",
                "passwordCredentials": [
                    {"displayName": "soon-secret", "endDateTime": "2026-10-30T00:00:00Z"},  # 15 -> EXPIRING SOON
                    {"displayName": "valid-secret", "endDateTime": "2027-03-01T00:00:00Z"},  # >90 -> Valid
                    {"displayName": "unknown-secret", "endDateTime": None},  # UNKNOWN
                ],
                "keyCredentials": [],
            }
        ]
        result, html_out = self._run_audit(applications, [])
        self.assertEqual(result["counts_by_status"], {"EXPIRING SOON": 1, "Valid": 1, "UNKNOWN": 1})
        self.assertIn("signal--clear", html_out)
        self.assertIn("No immediate action", html_out)
        self.assertIn("No expired or critical credentials were found.", html_out)

    def test_write_report_oserror_returns_partial_error(self) -> None:
        mod = load_configured_module(TEST_CLIENT_ID)
        modules, _, _, _ = make_mock_dependencies(
            responses_by_url={
                self.APPS_URL: FakeResponse(200, {"value": []}),
                self.SPS_URL: FakeResponse(200, {"value": []}),
            }
        )
        with (
            patch.dict(sys.modules, modules),
            patch.object(os, "makedirs", side_effect=OSError("Read-only file system")),
        ):
            result = mod.main()
        self.assertEqual(result["coverage"], "partial")
        self.assertIn("Failed to write report:", result["error"])
        self.assertIn("Read-only file system", result["error"])


class DocumentationAndLogoHelperTests(unittest.TestCase):
    def test_readme_optional_company_logo_oneliner_executes_cleanly(self) -> None:
        readme_text = README_PATH.read_text(encoding="utf-8")
        match = re.search(
            r'python -c "(import base64, sys, textwrap; from pathlib import Path;[^"]+)"',
            readme_text,
        )
        self.assertIsNotNone(match, "Could not find optional company logo one-liner in README.md")
        code_template = match.group(1)

        sample_png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        with tempfile.TemporaryDirectory(dir=TESTS_DIR) as temp_dir:
            logo_file = Path(temp_dir) / "company-logo.png"
            logo_file.write_bytes(sample_png)
            code = code_template.replace(r"C:\path\company-logo.png", str(logo_file))
            proc = subprocess.run(
                [sys.executable, "-c", code],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            dedented = textwrap.dedent(proc.stdout)
            output_lines = dedented.splitlines()
            self.assertGreaterEqual(len(output_lines), 3)
            for line in output_lines:
                self.assertLessEqual(len(line), 94, f"Output line exceeds 94 chars: {line}")

            namespace: dict[str, object] = {}
            exec(dedented, namespace)
            expected_uri = "data:image/png;base64," + base64.b64encode(sample_png).decode("ascii")
            self.assertEqual(namespace.get("company_logo_data_uri"), expected_uri)

    def test_markdown_links_anchors_and_images_resolve(self) -> None:
        def slugify(heading: str) -> str:
            slug = heading.strip().lower()
            slug = re.sub(r"[^\w\s-]", "", slug)
            return slug.replace(" ", "-")

        md_files = [README_PATH, SKILL_PATH, PROMPTS_PATH]
        anchors_by_file: dict[Path, set[str]] = {}
        for md_file in md_files:
            self.assertTrue(md_file.is_file(), f"Missing markdown file: {md_file}")
            content = md_file.read_text(encoding="utf-8")
            stripped = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
            headings = re.findall(r"^#{1,6}\s+(.+?)\s*$", stripped, flags=re.MULTILINE)
            anchors_by_file[md_file] = {slugify(h) for h in headings}

        link_pattern = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
        for md_file in md_files:
            content = md_file.read_text(encoding="utf-8")
            stripped = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
            for raw_target in link_pattern.findall(stripped):
                target = raw_target.strip()
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                path_part, _, fragment = target.partition("#")
                resolved_path = (md_file.parent / path_part).resolve() if path_part else md_file.resolve()
                self.assertTrue(
                    resolved_path.exists(),
                    f"Broken relative path '{target}' in {md_file.name}",
                )
                if fragment:
                    target_anchors = anchors_by_file.get(resolved_path)
                    if target_anchors is None and resolved_path.is_file():
                        target_text = resolved_path.read_text(encoding="utf-8")
                        target_stripped = re.sub(r"```.*?```", "", target_text, flags=re.DOTALL)
                        target_headings = re.findall(
                            r"^#{1,6}\s+(.+?)\s*$", target_stripped, flags=re.MULTILINE
                        )
                        target_anchors = {slugify(h) for h in target_headings}
                    self.assertIsNotNone(target_anchors)
                    self.assertIn(
                        fragment,
                        target_anchors,
                        f"Broken anchor '#{fragment}' in {md_file.name} -> {resolved_path.name}",
                    )


if __name__ == "__main__":
    unittest.main()
