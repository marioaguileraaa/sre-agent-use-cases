"""Generic package/documentation checks; no cloud or publication operations."""

import ast
import io
import json
import os
import re
import sys
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from support import CASE, TOOL


class PackageTests(unittest.TestCase):
    def test_local_guide_links_exist_and_inline_captures_use_packaged_pngs(self):
        import subprocess
        import tempfile
        from PIL import Image

        def heading_slugs(markdown_text: str) -> set[str]:
            stripped = re.sub(r"```.*?```", "", markdown_text, flags=re.S)
            slugs = set()
            for line in stripped.splitlines():
                match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
                if not match:
                    continue
                raw = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", match.group(1)).replace("`", "")
                slug = re.sub(r"[^\w\s-]", "", raw.lower())
                slugs.add(re.sub(r"\s+", "-", slug.strip()))
            return slugs

        for path in CASE.rglob("*.md"):
            content = path.read_text(encoding="utf-8")
            stripped = re.sub(r"```.*?```", "", content, flags=re.S)
            for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", stripped):
                if target.startswith(("https://", "http://")):
                    continue
                file_part, _, anchor = target.partition("#")
                resolved = (path.parent / file_part).resolve() if file_part else path.resolve()
                self.assertTrue(resolved.exists(), str(path.name) + " -> " + target)
                if anchor:
                    target_slugs = heading_slugs(resolved.read_text(encoding="utf-8"))
                    self.assertIn(anchor, target_slugs, f"{path.name} -> {target} (missing #{anchor})")
        readme = (CASE / "README.md").read_text(encoding="utf-8")
        self.assertIn("Not collected", readme)
        captures = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme)
        self.assertTrue(captures)
        actual_captures = {path.relative_to(CASE).as_posix() for path in (CASE / "images").glob("*.png")}
        for target in captures:
            self.assertIn(target, actual_captures)
            self.assertTrue((CASE / target).is_file(), target)
        self.assertNotIn("ASR-only", readme)

        match = re.search(r'python -c "(import base64, sys, textwrap;[^"]+)"', readme)
        self.assertIsNotNone(match, "README.md must include the copy-ready COMPANY_LOGO_DATA_URI generator one-liner")
        with tempfile.TemporaryDirectory() as temporary:
            logo_path = Path(temporary) / "company-logo.png"
            Image.new("RGB", (64, 24), "#FBC807").save(logo_path, format="PNG")
            code = match.group(1).replace(r"C:\path\company-logo.png", str(logo_path))
            completed = subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
            lines = completed.stdout.strip().splitlines()
            self.assertGreaterEqual(len(lines), 3)
            self.assertTrue(all(len(line) <= 94 for line in lines), lines)
            namespace = {}
            exec(completed.stdout, namespace)
            with patch.object(TOOL, "COMPANY_LOGO_DATA_URI", namespace["COMPANY_LOGO_DATA_URI"]):
                validated = TOOL.validate_branding()
                self.assertEqual(validated["logo"], namespace["COMPANY_LOGO_DATA_URI"])

    def test_single_runtime_skill_and_standalone_source_editor_lines(self):
        skills = list((CASE / "skills").rglob("SKILL.md"))
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0].parent.name, "azure-backup-live")
        source = (CASE / "generate-azure-backup-report.py").read_text(encoding="utf-8")
        self.assertLess(max(len(line) for line in source.splitlines()), 10_000)
        tree = ast.parse(source)
        self.assertEqual(sum(isinstance(node, ast.FunctionDef) and node.name == "main" for node in tree.body), 1)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertFalse((node.module or "").startswith(("case03", "case04", "engine", "support")))
        self.assertIn('CLIENT_NAME = "CLIENTE"', source)
        self.assertIn('COMPANY_LOGO_DATA_URI = ""', source)
        self.assertNotIn("DefaultAzureCredential", source)
        self.assertNotIn("AzureCliCredential", source)

    def test_definition_exec_has_no_runtime_activity_even_as_main(self):
        path = CASE / "generate-azure-backup-report.py"
        code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
        for module_name in ("__main__", "sre_hydrated_tool"):
            with self.subTest(module_name=module_name):
                forbidden_runtime = Mock(side_effect=AssertionError("Definition loading must not invoke main, collection or report writing."))

                def forbid_runtime_calls(frame, event, argument):
                    if event == "call" and frame.f_code.co_filename == str(path) and frame.f_code.co_name in (
                        "main", "collect_snapshot", "write_report",
                    ):
                        forbidden_runtime()

                namespace = {"__name__": module_name, "__file__": str(path)}
                output = io.StringIO()
                previous_profile = sys.getprofile()
                with ExitStack() as stack, redirect_stdout(output):
                    guards = [
                        stack.enter_context(patch(target, side_effect=AssertionError("Definition loading must not access network, cwd or files.")))
                        for target in (
                            "builtins.open", "pathlib.Path.open", "pathlib.Path.cwd", "socket.create_connection",
                            "urllib.request.OpenerDirector.open", "tempfile.mkstemp", "os.link",
                        )
                    ]
                    try:
                        sys.setprofile(forbid_runtime_calls)
                        exec(code, namespace)
                    finally:
                        sys.setprofile(previous_profile)
                self.assertTrue(callable(namespace["main"]))
                self.assertEqual(output.getvalue(), "")
                forbidden_runtime.assert_not_called()
                for guard in guards:
                    guard.assert_not_called()

    def test_product_design_surface_records_are_scoped_and_valid(self):
        for name in ("PRODUCT.md", "DESIGN.md", "SURFACE.md"):
            self.assertTrue((CASE / name).is_file())
        self.assertIn("<!-- impeccable:product-schema 1 -->", (CASE / "PRODUCT.md").read_text())
        design = json.loads((CASE / ".impeccable" / "design.json").read_text())
        self.assertEqual(design["schemaVersion"], 2)
        self.assertGreaterEqual(len(design["components"]), 5)
        for component in design["components"]:
            self.assertIn("ds-", component["html"])
            self.assertNotIn("https://", component["html"])

    @unittest.skipUnless(os.environ.get("CASE06_PRIVATE_REPLAY_PATH"), "Optional private fixture is unavailable for privacy comparison.")
    def test_recorded_private_scope_identifiers_are_not_in_generic_files(self):
        private = json.loads(Path(os.environ["CASE06_PRIVATE_REPLAY_PATH"]).read_text(encoding="utf-8-sig"))
        values = [private.get("subscription_id"), *private.get("identity", {}).values(), *private.get("approved_vault_ids_observed", [])]
        identifiers = set()
        for value in values:
            if isinstance(value, str):
                identifiers.update(re.findall(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value))
        self.assertTrue(identifiers)
        for path in CASE.rglob("*"):
            if not path.is_file() or path.suffix not in (".md", ".py", ".json", ".txt"):
                continue
            content = path.read_text(encoding="utf-8").casefold()
            for identifier in identifiers:
                self.assertNotIn(identifier.casefold(), content, path.name + " contains a private scope identifier")


if __name__ == "__main__":
    unittest.main()
