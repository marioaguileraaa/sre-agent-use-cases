import hashlib
import json
import struct
import unittest
from PIL import Image

from support import ROOT


class MediaAndDocumentationTests(unittest.TestCase):
    def test_visual_evidence_manifest_and_11_approved_pngs(self):
        manifest_path = ROOT / "visual-evidence.json"
        self.assertTrue(manifest_path.is_file())
        raw_text = manifest_path.read_text(encoding="utf-8")
        self.assertNotIn("private_source_path", raw_text)
        self.assertNotIn("C:\\Users", raw_text)
        self.assertNotIn(".copilot", raw_text)
        manifest = json.loads(raw_text)
        self.assertEqual(manifest["status"], "PARENT_VISUALLY_REVIEWED_READINESS_IMAGES_ONLY")
        images = manifest["images"]
        self.assertEqual(len(images), 16)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        for item in images:
            filename = item["filename"]
            img_path = ROOT / "images" / filename
            self.assertTrue(img_path.is_file(), f"Missing image {filename}")
            data = img_path.read_bytes()
            self.assertEqual(len(data), item["bytes"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"])
            self.assertIn(
                item["customer_source_assessment"],
                ("NOT_CONFIGURED_NOT_RUN", "CONNECTED_CROSS_TENANT_PARTIAL_LIVE_RUN"),
            )
            self.assertTrue(item["privacy_and_annotation_pixel_proof"])
            self.assertTrue(item["PNG_metadata_absent"])
            self.assertIn("images/" + filename, readme)

            with Image.open(img_path) as im:
                self.assertEqual(im.format, "PNG")
                self.assertEqual(im.size, (item["width"], item["height"]))

            # Verify PNG has no text/EXIF metadata chunks
            pos = 8
            while pos < len(data):
                length = struct.unpack(">I", data[pos:pos + 4])[0]
                chunk_type = data[pos + 4:pos + 8]
                self.assertNotIn(chunk_type, (b"tEXt", b"zTXt", b"iTXt", b"eXIf"))
                pos += 12 + length

    def test_native_readiness_validation_receipt_and_frozen_blob_hashes(self):
        receipt_path = ROOT / "native-readiness-validation.json"
        self.assertTrue(receipt_path.is_file())
        raw_bytes = receipt_path.read_bytes()
        receipt = json.loads(raw_bytes.decode("utf-8"))
        self.assertEqual(receipt["canonical_source_commit"], "9cd491266d71df981817b05b325e2bab7482ecc1")
        self.assertTrue(receipt["bootstrap_saved_and_independently_read_back"])
        self.assertTrue(receipt["full_skill_and_instruction_block_matched_committed_bytes"])
        self.assertIsNone(receipt["native_model_override"])
        self.assertEqual(receipt["actual_saved_tool_runtime"]["timeoutSeconds"], 900)
        self.assertFalse(receipt["actual_saved_tool_runtime"]["authEnabled"])
        self.assertEqual(receipt["native_parameters"], 12)
        self.assertEqual(receipt["native_integer_parameters"], ["limit", "offset"])
        self.assertEqual(
            receipt["native_python_tests"]["actual_domain_result"]["error"]["code"],
            "configuration_required",
        )
        self.assertEqual(
            receipt["native_python_tests"]["actual_domain_result"]["artifact_status"],
            "not_written",
        )
        self.assertEqual(
            receipt["customer_target_tenant_subscription_workspace_and_access"],
            "UNKNOWN_NOT_CONFIGURED",
        )
        self.assertEqual(receipt["real_Databricks_acceptance"], "NOT_RUN")
        self.assertEqual(receipt["media"]["actual_annotated_photographs"], 11)

        # Verify committed LF blob SHA-256 parity on the 4 frozen runtime files
        expected_blobs = receipt["canonical_runtime_files_sha256"]
        for rel_path, expected_sha in expected_blobs.items():
            lf_bytes = (ROOT / rel_path).read_bytes().replace(b"\r\n", b"\n")
            self.assertEqual(hashlib.sha256(lf_bytes).hexdigest(), expected_sha, f"Frozen file modified: {rel_path}")

    def test_readme_plane2_acl_matrix_and_readiness_disclosures(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("https://learn.microsoft.com/en-us/azure/databricks/security/auth/access-control", readme)
        self.assertIn("NO PERMISSIONS`, `CAN ATTACH TO`, `CAN MANAGE` *(no `CAN VIEW` level exists)*", readme)
        self.assertIn("`CAN MONITOR` and `CAN USE` can start the warehouse and run queries", readme)
        self.assertIn("Function test succeeded", readme)
        self.assertIn("133` global tools / `54` skills", readme)
        self.assertIn("native-readiness-validation.json", readme)
        self.assertIn("visual-evidence.json", readme)


if __name__ == "__main__":
    unittest.main()
