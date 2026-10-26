"""Offline package, link/anchor/manifest, branding one-liner and bilingual prompt tests."""

import base64
import inspect
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from support import ROOT, load_engine


DOCS = (
    "README.md",
    "subagent-instructions-and-prompts.md",
    "operator/README.md",
    "PRODUCT.md",
    "DESIGN.md",
    "SURFACE.md",
    "skills/aks-waf-live/SKILL.md",
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
    def test_markdown_links_anchors_and_capture_manifest_images_resolve(self):
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
                    f"Relative link {target!r} in {relative} escapes Case 04 root",
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

        manifest_path = ROOT / "images" / "capture-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_files = set()
        for entry in manifest.get("captures", []):
            img_path = (ROOT / "images" / entry["filename"]).resolve()
            self.assertTrue(img_path.is_file(), f"Missing capture manifest image: {entry['filename']}")
            self.assertGreater(img_path.stat().st_size, 0)
            manifest_files.add(img_path)

        self.assertTrue(manifest_files.issubset(referenced_images))

    def test_readme_branding_oneliner_produces_valid_chunked_data_uri(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        match = re.search(r'```powershell\npython -c "([\s\S]*?)"\n```', readme)
        self.assertIsNotNone(match, "Missing branding PowerShell one-liner in README.md")
        snippet = match.group(1)

        buffer = io.BytesIO()
        Image.new("RGB", (120, 32), (15, 108, 189)).save(buffer, format="PNG")
        png_bytes = buffer.getvalue()
        expected_uri = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")

        with tempfile.TemporaryDirectory(prefix="case04-logo-doc-test-") as temporary:
            logo_path = Path(temporary) / "company-logo.png"
            logo_path.write_bytes(png_bytes)
            code = snippet.replace(r"C:\path\company-logo.png", str(logo_path))
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.splitlines()
            self.assertGreater(len(lines), 2)
            self.assertTrue(all(len(line) <= 94 for line in lines))
            namespace: dict[str, object] = {}
            exec(compile(result.stdout, "<case04-readme-logo>", "exec"), {"__builtins__": {}}, namespace)
            self.assertEqual(namespace["CLIENT_LOGO_DATA_URI"], expected_uri)

        engine = load_engine(standalone=True)
        engine.validate_logo(namespace["CLIENT_LOGO_DATA_URI"], "CLIENTE")

    def test_schema_matches_standalone_signature_and_prompts_are_bilingual(self):
        schema = json.loads((ROOT / "tool-parameters.schema.json").read_text(encoding="utf-8"))
        standalone = load_engine(standalone=True)
        signature = inspect.signature(standalone.main)
        properties = schema["properties"]

        self.assertEqual(len(properties), 12)
        self.assertEqual(len(signature.parameters), 12)
        self.assertEqual(set(signature.parameters), set(properties))
        for name, parameter in signature.parameters.items():
            prop = properties[name]
            expected_type = int if prop["type"] == "integer" else str
            self.assertIs(parameter.annotation, expected_type, name)
            self.assertEqual(parameter.default, prop["default"], name)

        self.assertEqual(set(properties["operation"]["enum"]), {"report", "query", "list_clusters"})
        self.assertEqual(set(properties["view"]["enum"]), set(standalone.VIEWS))
        self.assertEqual(set(properties["area"]["enum"]), {"all", *standalone.AREAS})
        self.assertEqual(set(properties["level"]["enum"]), {"all", *standalone.LEVELS})
        self.assertEqual(set(properties["severity"]["enum"]), {"all", *standalone.SEVERITIES})
        self.assertEqual(
            set(properties["status"]["enum"]),
            {"all", *standalone.CHECK_STATUSES, *standalone.SOURCE_STATUSES},
        )

        subagent_doc = (ROOT / "subagent-instructions-and-prompts.md").read_text(encoding="utf-8")
        readme_doc = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("## Spanish chat prompts", subagent_doc)
        self.assertIn("## English chat prompts", subagent_doc)
        for token in (
            "Genera la revision de configuracion de AKS",
            "Generate the complete read-only AKS configuration review",
            '"operation":"list_clusters"',
            '"cluster_names":"<APPROVED_AKS_NAME>,<APPROVED_SECOND_AKS_NAME>"',
            "query/coverage",
            "query/findings",
            "query/workloads",
            "query/finops",
            "query/summary",
        ):
            self.assertIn(token, subagent_doc, f"Missing {token!r} in subagent-instructions-and-prompts.md")

        for token in (
            "Genera la revision de configuracion de AKS",
            "Generate the complete read-only AKS configuration review",
            "listClusterUserCredential",
            "APPROVED_CLUSTERS",
            "cluster_name.enum",
            "aks-prod-01,aks-prod-02",
            "4d367ae72e6829f4b2eaed41d37e65edfa263ca83acca5dd7c454e8df887265d",
        ):
            self.assertIn(token, readme_doc, f"Missing {token!r} in README.md")


if __name__ == "__main__":
    unittest.main()
