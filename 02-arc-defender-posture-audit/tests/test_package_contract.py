"""Offline package contract, signature parity, logo helper, and documentation link tests for Use Case 02."""

from __future__ import annotations

import base64
import importlib.util
import inspect
import io
import json
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
from unittest.mock import patch

CASE_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
LIVE_SCRIPT = CASE_DIR / "generate-defender-cloud-report.py"
SIM_SCRIPT = CASE_DIR / "simulate-arc-defender-mercadona.py"
SCHEMA_PATH = CASE_DIR / "tool-parameters.schema.json"
README_PATH = CASE_DIR / "README.md"
PROMPTS_PATH = CASE_DIR / "subagent-instructions-and-prompts.md"
MONTHLY_PATH = CASE_DIR / "monthly-task-prompt.md"
LIVE_SKILL_PATH = CASE_DIR / "skills" / "defender-cloud-live" / "SKILL.md"
SIM_SKILL_PATH = CASE_DIR / "skills" / "arc-defender-mercadona" / "SKILL.md"


def load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackageContractTests(unittest.TestCase):
    def test_both_tools_have_safe_import_and_main_execution_and_line_lengths(self) -> None:
        for script_path in (LIVE_SCRIPT, SIM_SCRIPT):
            with self.subTest(script=script_path.name):
                raw_text = script_path.read_text(encoding="utf-8")
                lines = raw_text.splitlines()
                self.assertGreater(len(lines), 100)
                for idx, line in enumerate(lines, start=1):
                    self.assertLess(
                        len(line),
                        10_000,
                        f"{script_path.name}:{idx} exceeds 10,000 characters ({len(line)} chars)",
                    )

                stdout_buf = io.StringIO()
                with (
                    patch.object(socket, "create_connection", side_effect=AssertionError("Network call on load")),
                    patch.object(os, "makedirs", side_effect=AssertionError("os.makedirs called on load")),
                    patch("sys.stdout", stdout_buf),
                ):
                    load_module(script_path.stem + "_imported", script_path)
                    runpy.run_path(str(script_path), run_name="__main__")

                self.assertEqual(stdout_buf.getvalue(), "")

    def test_both_tools_expose_identical_15_parameter_signature_matching_schema(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        schema_props = schema["properties"]
        self.assertEqual(len(schema_props), 15)

        live_mod = load_module("live_contract", LIVE_SCRIPT)
        sim_mod = load_module("sim_contract", SIM_SCRIPT)

        live_sig = inspect.signature(live_mod.main)
        sim_sig = inspect.signature(sim_mod.main)
        self.assertEqual(list(live_sig.parameters.keys()), list(sim_sig.parameters.keys()))
        self.assertEqual(list(live_sig.parameters.keys()), list(schema_props.keys()))

        for name, prop in schema_props.items():
            live_param = live_sig.parameters[name]
            sim_param = sim_sig.parameters[name]
            self.assertEqual(live_param.default, sim_param.default, f"Default mismatch on {name}")
            self.assertEqual(live_param.default, prop["default"], f"Schema default mismatch on {name}")
            expected_type = int if prop["type"] == "integer" else str
            self.assertIn(live_param.annotation, (expected_type, expected_type.__name__))
            self.assertIn(sim_param.annotation, (expected_type, expected_type.__name__))

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

    def test_all_markdown_relative_links_anchors_and_images_resolve(self) -> None:
        def slugify(heading: str) -> str:
            slug = heading.strip().lower()
            slug = re.sub(r"[^\w\s-]", "", slug)
            return slug.replace(" ", "-")

        md_files = [
            README_PATH,
            PROMPTS_PATH,
            MONTHLY_PATH,
            LIVE_SKILL_PATH,
            SIM_SKILL_PATH,
        ]
        anchors_by_file: dict[Path, set[str]] = {}
        for md_file in md_files:
            self.assertTrue(md_file.is_file(), f"Missing markdown file: {md_file}")
            content = md_file.read_text(encoding="utf-8")
            stripped = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
            headings = re.findall(r"^#{1,6}\s+(.+?)\s*$", stripped, flags=re.MULTILINE)
            anchors_by_file[md_file.resolve()] = {slugify(h) for h in headings}

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
                    f"Broken relative path '{target}' in {md_file.relative_to(CASE_DIR)}",
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
                        f"Broken anchor '#{fragment}' in {md_file.relative_to(CASE_DIR)} -> {resolved_path.name}",
                    )


if __name__ == "__main__":
    unittest.main()
