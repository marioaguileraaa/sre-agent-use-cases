import copy
import json
import sys
import unittest
from html.parser import HTMLParser

from support import REFERENCE, ROOT, fixture, load_engine


class StructureParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.meta_csp = None

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        if "id" in attr_map:
            self.ids.add(attr_map["id"])
        if tag == "meta" and attr_map.get("http-equiv", "").lower() == "content-security-policy":
            self.meta_csp = attr_map.get("content")


class ReportUiTests(unittest.TestCase):
    def setUp(self):
        self.e = load_engine()
        self.raw = fixture(self.e)
        self.snapshot = self.e.finish_snapshot(self.raw, REFERENCE, "SIMULATED", "LAB")

    def test_html_render_roundtrip_csp_and_required_sections(self):
        html = self.e.render_html(self.snapshot)
        self.assertLessEqual(len(html.encode("utf-8")), 4_800_000)
        parser = StructureParser()
        parser.feed(html)
        self.assertIsNotNone(parser.meta_csp)
        self.assertIn("default-src 'none'", parser.meta_csp)
        self.assertIn("connect-src 'none'", parser.meta_csp)
        for required_id in (
            "sec-cover",
            "sec-executive",
            "sec-investigation",
            "sec-cycles",
            "sec-patches",
            "sec-extensions",
            "sec-actions",
            "sec-sources",
            "filter-category",
            "filter-hosting",
            "filter-severity",
            "filter-search",
            "filter-reset-btn",
            "machines-table",
            "cycles-table",
            "patches-table",
            "extensions-table",
            "actions-table",
            "sources-table",
            "theme-toggle",
            "export-json-btn",
            "export-machines-csv-btn",
            "export-patches-csv-btn",
            "print-btn",
            "report-data",
        ):
            self.assertIn(required_id, parser.ids)
        embedded = html.split('<script type="application/json" id="report-data">', 1)[1].split("</script>", 1)[0]
        self.assertEqual(json.loads(embedded), self.snapshot)

    def test_html_escapes_script_injection_in_embedded_json(self):
        poisoned = copy.deepcopy(self.snapshot)
        poisoned["machines"][0]["name"] = "</script><script>alert('xss')</script>&<>"
        html = self.e.render_html(poisoned)
        self.assertNotIn("</script><script>", html)
        embedded = html.split('<script type="application/json" id="report-data">', 1)[1].split("</script>", 1)[0]
        self.assertEqual(json.loads(embedded), poisoned)

    def test_swiss_architectural_palette_tokens_present(self):
        template = (ROOT / "report_template.html").read_text(encoding="utf-8")
        self.assertIn("--canvas: #F6F5F2", template)
        self.assertIn("--chrome: #141B24", template)
        self.assertIn("--accent: #FF4E00", template)
        self.assertIn("--accent-text: #C23800", template)
        self.assertIn("--line: #D8DCE3", template)

    def test_browser_interaction_filters_drawers_dark_mode_and_viewports(self):
        from playwright.sync_api import sync_playwright

        html = self.e.render_html(self.snapshot)
        with sync_playwright() as p:
            launch_kwargs = {"headless": True}
            if sys.platform == "win32":
                launch_kwargs["channel"] = "msedge"
            browser = p.chromium.launch(**launch_kwargs)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                errors = []
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                page.set_content(html, wait_until="load")
                self.assertEqual(errors, [])
                self.assertEqual(page.locator("#client-name-label").inner_text(), "CLIENTE")
                self.assertIn("Mostrando 9 de 9 máquinas.", page.locator("#machines-count-label").inner_text())

                # Filter by failure_category
                page.select_option("#filter-category", "assessment_stuck_or_readiness_undetermined")
                self.assertIn("Mostrando 2 de 9 máquinas.", page.locator("#machines-count-label").inner_text())

                # Filter by hotpatch_or_patch_extension_error (matches ArcBox-Client via matched_categories and vm-arc-win-04)
                page.select_option("#filter-category", "hotpatch_or_patch_extension_error")
                self.assertIn("Mostrando 2 de 9 máquinas.", page.locator("#machines-count-label").inner_text())

                # Reset filters
                page.click("#filter-reset-btn")
                self.assertIn("Mostrando 9 de 9 máquinas.", page.locator("#machines-count-label").inner_text())

                # Filter by hosting=arc and search
                page.select_option("#filter-hosting", "arc")
                self.assertIn("Mostrando 5 de 9 máquinas.", page.locator("#machines-count-label").inner_text())
                page.fill("#filter-search", "KB5128493")
                self.assertIn("Mostrando 1 de 9 máquinas.", page.locator("#machines-count-label").inner_text())
                page.click("#filter-reset-btn")

                # Collapse / expand drawers
                self.assertFalse(page.locator("#drawer-machine-0").is_hidden())
                page.click("#toggle-all-drawers-btn")
                self.assertTrue(page.locator("#drawer-machine-0").is_hidden())
                page.click("#toggle-all-drawers-btn")
                self.assertFalse(page.locator("#drawer-machine-0").is_hidden())

                # Dark mode toggle
                page.click("#theme-toggle")
                self.assertEqual(page.locator("html").get_attribute("data-theme"), "dark")

                # Responsive viewports: 1440px, 390px, 320px
                for width in (1440, 390, 320):
                    page.set_viewport_size({"width": width, "height": 844})
                    self.assertTrue(page.locator("#cover-title").is_visible())
                    overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
                    self.assertFalse(overflow, f"Horizontal overflow detected at {width}px")

                self.assertEqual(errors, [])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
