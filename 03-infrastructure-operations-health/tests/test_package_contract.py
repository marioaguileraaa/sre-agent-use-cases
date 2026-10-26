"""Offline package, hydration, link/anchor and bilingual prompt contract tests."""

import builtins
import inspect
import io
import json
import os
import re
import socket
import tempfile
import unittest
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "generate-infrastructure-operations-report.py"
SCHEMA_PATH = ROOT / "tool-parameters.schema.json"
DOCS = (
    "README.md",
    "subagent-instructions-and-prompts.md",
    "monthly-task-prompt.md",
    "PRODUCT.md",
    "DESIGN.md",
    "skills/infra-ops-live/SKILL.md",
)


def _github_slug(heading: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", heading.strip())
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return re.sub(r"\s", "-", text)


def _markdown_headings(path: Path) -> set[str]:
    slugs: set[str] = set()
    counts: dict[str, int] = {}
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match:
            base = _github_slug(match.group(1))
            occurrence = counts.get(base, 0)
            counts[base] = occurrence + 1
            slugs.add(base if occurrence == 0 else f"{base}-{occurrence}")
    return slugs


class PackageContractTests(unittest.TestCase):
    def test_sre_tool_hydration_as_main_has_zero_side_effects_and_matches_schema(self):
        source = TOOL_PATH.read_text(encoding="utf-8")
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        lines = source.splitlines()
        self.assertGreater(len(lines), 100)
        self.assertTrue(all(len(line) < 10_000 for line in lines))

        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name in ("azure", "azure.identity", "requests"):
                raise AssertionError(f"Hydration must not import runtime network/auth dependency {name!r}.")
            return original_import(name, *args, **kwargs)

        stdout = io.StringIO()
        namespace = {"__name__": "__main__", "__file__": str(TOOL_PATH)}
        with (
            patch("builtins.__import__", side_effect=guarded_import),
            patch.object(socket, "create_connection", side_effect=AssertionError("Unexpected socket connection")),
            patch.object(urllib.request, "urlopen", side_effect=AssertionError("Unexpected urllib call")),
            patch.object(Path, "mkdir", side_effect=AssertionError("Unexpected directory creation")),
            patch.object(tempfile, "mkstemp", side_effect=AssertionError("Unexpected file creation")),
            patch.object(os, "replace", side_effect=AssertionError("Unexpected file replacement")),
            redirect_stdout(stdout),
        ):
            exec(compile(source, str(TOOL_PATH), "exec"), namespace)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("main", namespace)
            result = namespace["main"]()

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "configuration_required")
        self.assertFalse(result["artifacts_created"])

        signature = inspect.signature(namespace["main"])
        properties = schema["properties"]
        self.assertEqual(len(signature.parameters), 16)
        self.assertEqual(list(signature.parameters), list(properties))
        for name, parameter in signature.parameters.items():
            prop = properties[name]
            expected_type = int if prop["type"] == "integer" else str
            self.assertIs(parameter.annotation, expected_type, name)
            self.assertEqual(parameter.default, prop["default"], name)

    def test_markdown_links_anchors_and_images_resolve(self):
        referenced_images: set[Path] = set()
        for relative in DOCS:
            doc_path = ROOT / relative
            self.assertTrue(doc_path.is_file(), f"Missing documentation file: {relative}")
            content = doc_path.read_text(encoding="utf-8")
            for match in re.finditer(r"!?\[[^\]]*\]\(([^)]+)\)", content):
                target = match.group(1).strip()
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                path_part, _, fragment = target.partition("#")
                resolved = (doc_path.parent / path_part).resolve() if path_part else doc_path.resolve()
                self.assertTrue(
                    resolved.exists(),
                    f"Unresolved relative path {target!r} in {relative}",
                )
                self.assertTrue(
                    resolved.is_relative_to(ROOT),
                    f"Relative link {target!r} in {relative} escapes Case 03 root",
                )
                if resolved.suffix.lower() == ".png":
                    self.assertGreater(resolved.stat().st_size, 0, f"Empty PNG {resolved}")
                    referenced_images.add(resolved)
                if fragment and not re.fullmatch(r"L\d+(?:-L\d+)?", fragment):
                    headings = _markdown_headings(resolved)
                    self.assertIn(
                        fragment,
                        headings,
                        f"Unresolved anchor #{fragment} in {relative} -> {resolved.name}",
                    )

        actual_images = {path.resolve() for path in (ROOT / "images").glob("*.png")}
        self.assertGreaterEqual(len(actual_images), 11)
        self.assertEqual(referenced_images, actual_images)

    def test_subagent_and_monthly_prompts_preserve_names_cron_and_bilingual_coverage(self):
        subagent_doc = (ROOT / "subagent-instructions-and-prompts.md").read_text(encoding="utf-8")
        monthly_doc = (ROOT / "monthly-task-prompt.md").read_text(encoding="utf-8")
        readme_doc = (ROOT / "README.md").read_text(encoding="utf-8")

        for text in (subagent_doc, monthly_doc, readme_doc):
            self.assertIn("generate-infrastructure-operations-report", text)
            self.assertIn("infra-ops-live", text)

        self.assertIn("0 9 1 * *", monthly_doc)
        self.assertIn("0 9 1 * *", readme_doc)
        self.assertIn('operation="report", period="previous_month"', monthly_doc)

        for required_spanish in (
            "Genera el informe real de infraestructura de las ultimas",
            "usa query/extensions, metric=all",
            "Para <ARC_RESOURCE_NAME>, usa query/metrics, hosting=arc",
        ):
            self.assertIn(required_spanish, subagent_doc)
            self.assertIn(required_spanish, readme_doc)

        for required_english in (
            "Generate the real read-only infrastructure report for the last",
            "query/extensions",
            "query/metrics",
        ):
            self.assertIn(required_english, subagent_doc)
            self.assertIn(required_english, readme_doc)

    def test_readme_portal_readback_tables_and_scale_gate_documented(self):
        readme_doc = (ROOT / "README.md").read_text(encoding="utf-8")
        normalized = re.sub(r"\s+", " ", readme_doc)
        table_header = "| Step | Portal surface & field | Value to enter / select | Readback checkpoint |"
        self.assertGreaterEqual(readme_doc.count(table_header), 4)
        for token in (
            "SUBSCRIPTION_ID",
            "TENANT_ID",
            "MANAGED_IDENTITY_CLIENT_ID",
            "LOG_WORKSPACE_IDS",
            "ARC_ADMIN_BASELINES",
            "900",
            "500",
            "allowedSkills",
            "disableDocumentRetrieval=true",
            "141 tests run; 131 passed, 10 pre-existing optional/private/platform skips",
        ):
            self.assertIn(token, normalized, f"Missing expected token in README.md: {token!r}")


if __name__ == "__main__":
    unittest.main()
