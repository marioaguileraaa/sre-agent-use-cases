"""Bounded desktop/mobile browser checks using SIMULATED evidence only."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from support import BRANDING, PRECISE_INTEGER, TOOL, VAULT_B, simulated_snapshot


class OfflineUiTests(unittest.TestCase):
    def test_desktop_mobile_keyboard_filters_exact_downloads_and_print(self):
        from playwright.sync_api import sync_playwright

        snapshot, _ = simulated_snapshot(extra_completed=55)
        data = TOOL.prepare_artifacts(snapshot, BRANDING)
        with tempfile.TemporaryDirectory(prefix="case06-browser-") as temporary, sync_playwright() as playwright:
            root = Path(temporary)
            document = root / "SIMULATED-azure-backup.html"
            document.write_bytes(data["report_path"])
            artifacts = Path(os.environ["CASE06_UI_ARTIFACT_DIR"]) if os.environ.get("CASE06_UI_ARTIFACT_DIR") else root / "captures"
            artifacts.mkdir(parents=True, exist_ok=True)
            channel = os.environ.get("CASE06_BROWSER_CHANNEL", "msedge" if os.name == "nt" else "")
            browser = playwright.chromium.launch(headless=True, **({"channel": channel} if channel else {}))
            context = browser.new_context(accept_downloads=True, viewport={"width": 1440, "height": 1000})
            requests, errors = [], []
            context.on("request", lambda request: requests.append(request.url))
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(document.as_uri(), wait_until="load")
            page.wait_for_selector("#report:not([hidden])")

            measurements = []
            for name, width, height in (("desktop", 1440, 1000), ("mobile", 390, 844), ("small-mobile", 320, 900)):
                page.set_viewport_size({"width": width, "height": height})
                page.screenshot(path=str(artifacts / ("SIMULATED-" + name + ".png")), full_page=False)
                measurements.append(page.evaluate("""() => ({
                  width: innerWidth, documentWidth: document.documentElement.scrollWidth,
                  bodyWidth: document.body.scrollWidth,
                  minControlHeight: Math.min(...[...document.querySelectorAll("button,input,select")].map(node => node.getBoundingClientRect().height)),
                  h1: getComputedStyle(document.querySelector("h1")).fontSize,
                  brand: getComputedStyle(document.querySelector(".brand-frame")).backgroundColor,
                  ink: getComputedStyle(document.querySelector(".brand-frame")).color
                })"""))
            for value in measurements:
                self.assertLessEqual(value["documentWidth"], value["width"] + 1, value)
                self.assertLessEqual(value["bodyWidth"], value["width"] + 1, value)
                self.assertGreaterEqual(value["minControlHeight"], 44, value)
                self.assertEqual(value["brand"], "rgb(251, 200, 7)")
                self.assertEqual(value["ink"], "rgb(30, 28, 24)")

            page.set_viewport_size({"width": 1440, "height": 1000})
            self.assertIn("SIMULATED", page.locator("#provenance").inner_text())
            self.assertIn("Unknown", page.locator(".count-strip").inner_text())
            self.assertEqual(page.locator("#jobs-body > tr").count(), 40)
            page.locator("#next").click()
            self.assertGreater(page.locator("#jobs-body > tr").count(), 0)
            self.assertLess(page.locator("#jobs-body > tr").count(), 40)
            page.locator("#previous").click()

            page.locator("#state-filter").select_option(json.dumps("Failed"))
            self.assertEqual(page.locator("#jobs-body > tr").count(), 3)
            self.assertIn("List: Failed", page.locator("#jobs-body").inner_text())
            for button_id, expected in (("export-json", data["snapshot_path"]), ("export-jobs", data["jobs_csv_path"]),
                                        ("export-coverage", data["coverage_csv_path"])):
                with page.expect_download() as download_info:
                    page.locator("#" + button_id).click()
                self.assertEqual(Path(download_info.value.path()).read_bytes(), expected)
            self.assertEqual(json.loads(data["snapshot_path"])["jobs"][0]["list_ref"]["row"], 0)

            page.locator("#reset").click()
            page.locator("#operation-filter").select_option(json.dumps("Restore"))
            self.assertEqual(page.locator("#jobs-body > tr").count(), 1)
            self.assertIn("restore", page.locator("#jobs-body").inner_text().lower())
            page.locator("#reset").click()
            page.locator("#window-filter").select_option("unknown")
            self.assertEqual(page.locator("#jobs-body > tr").count(), 1)
            page.locator("#window-filter").select_option("all")
            self.assertIn("75 received", page.locator("#filter-summary").inner_text())
            page.locator("#job-filter").fill("synthetic-0")
            self.assertEqual(page.locator("#jobs-body > tr").count(), 1)
            page.locator("#jobs-body details summary").click()
            evidence = page.locator("#jobs-body pre").inner_text()
            self.assertIn(str(PRECISE_INTEGER), evidence)
            self.assertIn('"</script><img', evidence)
            self.assertEqual(page.locator('img[src^="https:"]').count(), 0)
            self.assertIsNone(page.evaluate("window.__injected"))
            page.locator("#reset").click()

            page.locator("#vault-filter").select_option(VAULT_B)
            self.assertTrue(page.locator("#jobs-empty").is_visible())
            self.assertIn("does not establish", page.locator("#jobs-empty").inner_text())
            self.assertEqual(page.locator("#items-body > tr").count(), 1)
            self.assertEqual(page.locator("#history-body > tr").count(), 1)
            self.assertEqual(page.locator("#sources-body > tr").count(), 4)
            self.assertIn("Unknown", page.locator("#items-body").inner_text())
            page.locator("#reset").click()
            page.locator("#today").click()
            self.assertEqual(page.locator("#window-filter").input_value(), "last24")
            self.assertEqual(page.evaluate("document.activeElement.id"), "window-filter")
            page.locator("#reset").click()

            page.reload(wait_until="load")
            page.wait_for_selector("#report:not([hidden])")
            page.keyboard.press("Tab")
            self.assertEqual(page.evaluate("document.activeElement.className"), "skip")
            self.assertEqual(page.evaluate("getComputedStyle(document.activeElement).outlineStyle"), "solid")
            page.keyboard.press("Enter")
            self.assertEqual(page.evaluate("document.activeElement.id"), "main")

            page.evaluate("dispatchEvent(new Event('beforeprint'))")
            expected_matching = sum(row["window_membership"] == "in_requested_window" for row in snapshot["jobs"])
            self.assertEqual(page.locator("#jobs-body > tr").count(), expected_matching)
            self.assertEqual(page.locator("details:not([open])").count(), 0)
            page.emulate_media(media="print")
            self.assertEqual(page.locator("#export-json").evaluate("(node) => getComputedStyle(node).display"), "none")
            pdf = page.pdf(format="A4", landscape=True, print_background=True)
            self.assertTrue(pdf.startswith(b"%PDF-"))
            self.assertGreater(len(pdf), 10000)
            page.emulate_media(media="screen")
            page.evaluate("dispatchEvent(new Event('afterprint'))")
            self.assertEqual(page.locator("#jobs-body > tr").count(), 40)
            self.assertFalse(page.locator("#fatal").is_visible())
            self.assertEqual(errors, [])
            self.assertFalse(any(url.startswith(("https:", "http:")) for url in requests), requests)
            (artifacts / "SIMULATED-ui-receipt.json").write_text(json.dumps({
                "provenance": "SIMULATED", "viewports": measurements, "job_records": len(snapshot["jobs"]),
                "print_matching_records": expected_matching, "exact_downloads": 3, "http_requests": 0,
                "page_errors": errors, "pdf_bytes": len(pdf), "screenshots_are_not_live_evidence": True,
            }, indent=2), encoding="utf-8")
            context.close()
            browser.close()


if __name__ == "__main__":
    unittest.main()
