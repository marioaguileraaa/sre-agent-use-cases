"""Offline logo-only regression tests; generated rasters are test fixtures."""

import base64
import binascii
import builtins
import io
import json
import re
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from test_infrastructure_operations import REFERENCE, snapshot, tool


def raster_uri(fmt="PNG", size=(120, 32)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (22, 61, 58)).save(buffer, format=fmt)
    return "data:image/" + ("png" if fmt == "PNG" else "jpeg") + ";base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


class CompanyLogoTests(unittest.TestCase):
    def test_empty_configuration_keeps_exact_placeholder_without_loading_pillow(self):
        original = builtins.__import__

        def no_pillow(name, *args, **kwargs):
            if name == "PIL" or name.startswith("PIL."):
                raise AssertionError("Default placeholder must not import an optional raster dependency.")
            return original(name, *args, **kwargs)

        with patch.object(tool, "COMPANY_LOGO_DATA_URI", ""), patch("builtins.__import__", side_effect=no_pillow):
            self.assertEqual(tool._company_logo_markup(), '<span class="company-logo-placeholder">logo company</span>')
            rendered = tool._render_html(snapshot())
        self.assertIn("logo company", rendered)
        self.assertIn('id="provenance-label"', rendered)
        self.assertIn('id="collected-time"', rendered)
        self.assertNotIn('src="http', rendered)

    def test_embedded_png_and_jpeg_are_validated_and_contained_with_alt_text(self):
        for fmt in ("PNG", "JPEG"):
            uri = raster_uri(fmt)
            with self.subTest(format=fmt), patch.object(tool, "COMPANY_LOGO_DATA_URI", uri), \
                 patch.object(tool, "COMPANY_LOGO_ALT_TEXT", "Example company logo"):
                markup = tool._company_logo_markup()
                self.assertIn('src="' + uri + '"', markup)
                self.assertIn('alt="Example company logo"', markup)
                self.assertIn('width="120" height="32"', markup)
                self.assertNotIn("logo company", markup)

    def test_invalid_nonempty_logo_is_an_explicit_error_never_a_silent_placeholder(self):
        valid = raster_uri()
        bad = (
            None, " ", "https://example.com/logo.png", "file:///logo.png",
            "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=", "data:image/gif;base64,R0lGODlh",
            "data:image/png;base64,", "data:image/png;base64,abc",
            "data:image/png;base64," + base64.b64encode(b"not a PNG").decode("ascii"),
            valid.replace("image/png", "image/jpeg"),
        )
        for value in bad:
            with self.subTest(value=str(value)[:45]), patch.object(tool, "COMPANY_LOGO_DATA_URI", value):
                with self.assertRaises(tool.EvidenceError) as caught:
                    tool._company_logo_markup()
                self.assertEqual(caught.exception.source, "company_logo")

    def test_payload_dimensions_and_animation_are_bounded(self):
        oversized = "data:image/png;base64," + base64.b64encode(b"x" * 100_001).decode("ascii")
        animation = io.BytesIO()
        first, second = Image.new("RGB", (16, 16), "white"), Image.new("RGB", (16, 16), "black")
        first.save(animation, format="PNG", save_all=True, append_images=[second], duration=100)
        animated = "data:image/png;base64," + base64.b64encode(animation.getvalue()).decode("ascii")
        for uri in (oversized, raster_uri(size=(2049, 1)), raster_uri(size=(1, 2049)), animated):
            with self.subTest(length=len(uri)), patch.object(tool, "COMPANY_LOGO_DATA_URI", uri), \
                 self.assertRaises(tool.EvidenceError):
                tool._company_logo_markup()
        truncated = raster_uri("JPEG")
        bytes_ = base64.b64decode(truncated.split(",", 1)[1])
        with patch.object(tool, "COMPANY_LOGO_DATA_URI", "data:image/jpeg;base64," + base64.b64encode(bytes_[:-10]).decode("ascii")), \
             self.assertRaises(tool.EvidenceError):
            tool._company_logo_markup()

    def test_corrupt_png_checksum_is_an_explicit_logo_error(self):
        data = bytearray(base64.b64decode(raster_uri().split(",", 1)[1]))
        offset = data.index(b"IDAT")
        length = int.from_bytes(data[offset - 4:offset], "big")
        data[offset + 4 + length] ^= 1
        with patch.object(tool, "COMPANY_LOGO_DATA_URI", "data:image/png;base64," + base64.b64encode(data).decode("ascii")), \
             self.assertRaises(tool.EvidenceError) as caught:
            tool._company_logo_markup()
        self.assertEqual(caught.exception.code, "invalid_company_logo")

    def test_exact_raster_size_limit_is_inclusive(self):
        data = base64.b64decode(raster_uri().split(",", 1)[1])
        padding = b"fixture\x00" + b"x" * (100_000 - len(data) - 12 - 8)
        chunk = len(padding).to_bytes(4, "big") + b"tEXt" + padding + (binascii.crc32(b"tEXt" + padding) & 0xffffffff).to_bytes(4, "big")
        image = data[:-12] + chunk + data[-12:]
        self.assertEqual(len(image), 100_000)
        with patch.object(tool, "COMPANY_LOGO_DATA_URI", "data:image/png;base64," + base64.b64encode(image).decode("ascii")):
            self.assertIn('<img src="data:image/png;base64,', tool._company_logo_markup())

    def test_readme_generator_produces_short_valid_code_chunks(self):
        readme = (Path(tool.__file__).parent / "README.md").read_text(encoding="utf-8")
        snippet = re.search(r'```powershell\npython -c "([\s\S]*?)"\n```', readme)[1]
        with tempfile.TemporaryDirectory(prefix="case03-logo-doc-test-") as temporary:
            path = Path(temporary) / "company-logo.png"
            path.write_bytes(base64.b64decode(raster_uri().split(",", 1)[1]))
            code = snippet.replace(r"C:\path\company-logo.png", str(path))
            result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(all(len(line) <= 94 for line in result.stdout.splitlines()))
            compiled = compile(result.stdout, "<readme logo configuration>", "exec")
            namespace = {}
            exec(compiled, {"__builtins__": {}}, namespace)
            self.assertEqual(namespace["COMPANY_LOGO_DATA_URI"], raster_uri())

    def test_alt_text_is_descriptive_bounded_and_html_escaped(self):
        with patch.object(tool, "COMPANY_LOGO_DATA_URI", raster_uri()):
            for alt in ("", " ", "x" * 121, "logo\ncompany", None):
                with self.subTest(alt=alt), patch.object(tool, "COMPANY_LOGO_ALT_TEXT", alt), self.assertRaises(tool.EvidenceError):
                    tool._company_logo_markup()
            with patch.object(tool, "COMPANY_LOGO_ALT_TEXT", 'Test "company" <logo>'):
                self.assertIn('alt="Test &quot;company&quot; &lt;logo&gt;"', tool._company_logo_markup())

    def test_optional_missing_dependency_is_reported_not_hidden(self):
        original = builtins.__import__

        def no_pillow(name, *args, **kwargs):
            if name == "PIL" or name.startswith("PIL."):
                raise ImportError("Synthetic missing optional dependency.")
            return original(name, *args, **kwargs)

        with patch.object(tool, "COMPANY_LOGO_DATA_URI", raster_uri()), \
             patch("builtins.__import__", side_effect=no_pillow), self.assertRaises(tool.EvidenceError) as caught:
            tool._company_logo_markup()
        self.assertEqual(caught.exception.code, "dependency_missing")

    def test_invalid_report_logo_fails_before_collection_but_queries_are_unchanged(self):
        data = snapshot()
        with patch.object(tool, "COMPANY_LOGO_DATA_URI", "https://example.com/logo.png"), \
             patch.object(tool, "_config", return_value={}) as config, \
             patch.object(tool, "_collect_live", return_value=data) as collect, \
             patch.object(tool, "_utc_now", return_value=REFERENCE):
            response = tool.main(operation="report")
            self.assertEqual(response["status"], "error")
            self.assertEqual(response["error"]["code"], "invalid_company_logo")
            config.assert_not_called()
            collect.assert_not_called()
            query = tool.main(operation="query")
            self.assertNotEqual(query["status"], "error")
            self.assertEqual(query["summary"], data["summary"])
        self.assertLessEqual(len(json.dumps(response).encode("utf-8")), 3500)

    def test_logo_does_not_change_snapshot_exports_or_response_shape(self):
        data = snapshot()
        encoded = tool._json_document(data)
        with tempfile.TemporaryDirectory(prefix="case03-logo-test-") as temporary:
            with patch.object(tool.Path, "cwd", return_value=Path(temporary)):
                baseline = tool._write_report(data)
                with patch.object(tool, "COMPANY_LOGO_DATA_URI", raster_uri()), \
                     patch.object(tool, "COMPANY_LOGO_ALT_TEXT", "__SNAPSHOT_DATA__"):
                    branded = tool._write_report(data)
            self.assertEqual(set(branded), set(baseline))
            self.assertEqual(branded["summary"], baseline["summary"])
            for key in ("snapshot_path", "resources_csv_path", "signals_csv_path"):
                self.assertEqual(Path(branded[key]).read_bytes(), Path(baseline[key]).read_bytes())
            markup = Path(branded["report_path"]).read_text(encoding="utf-8")
            blob = re.search(r'<script id="evidence-data" type="application/json">([\s\S]*?)</script>', markup)[1]
            self.assertEqual(tool._unpack_snapshot(json.loads(blob)), data)
            self.assertEqual(Path(branded["snapshot_path"]).read_text(encoding="utf-8"), encoded)
            self.assertIn('alt="__SNAPSHOT_DATA__"', markup)
            self.assertNotIn("data:image", json.dumps(branded))
            self.assertLessEqual(len(json.dumps(branded).encode("utf-8")), 3500)
            self.assertTrue(all(Path(branded[key]).stat().st_size <= 4_800_000
                                for key in ("report_path", "snapshot_path", "resources_csv_path", "signals_csv_path")))

    def test_logo_bytes_count_against_the_existing_no_truncation_artifact_limit(self):
        data = snapshot()
        with patch.object(tool, "COMPANY_LOGO_DATA_URI", ""):
            plain_size = len(tool._render_html(data).encode("utf-8"))
        with tempfile.TemporaryDirectory(prefix="case03-logo-limit-test-") as temporary:
            root = Path(temporary)
            with patch.object(tool.Path, "cwd", return_value=root), patch.object(tool, "MAX_ARTIFACT_BYTES", plain_size), \
                 patch.object(tool, "COMPANY_LOGO_DATA_URI", raster_uri()), self.assertRaises(tool.EvidenceError) as caught:
                tool._write_report(data)
            self.assertEqual(caught.exception.code, "artifact_size_exceeded")
            self.assertFalse((root / "infrastructure-operations-reports").exists())


if __name__ == "__main__":
    unittest.main()
