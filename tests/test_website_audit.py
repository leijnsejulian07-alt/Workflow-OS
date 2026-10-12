"""Regression checks for the entirely offline website audit candidate."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from workflow_os.website_audit import (
    MAX_PAGE_BYTES,
    MAX_PAGES,
    audit_html_pages,
    audit_local_site,
    load_local_html_pages,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_website_audit.py"

GOOD_HTML = """<!doctype html><html lang="nl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Example of a local business website">
<title>Voorbeeldbedrijf</title></head><body><main>
<h1>Welkom</h1><img src="photo.png" alt="Winkelpand">
<nav><a href="/about/">Over ons</a></nav>
<a href="mailto:info@example.com">Contact</a>
</main></body></html>"""
ABOUT_HTML = GOOD_HTML.replace('<a href="/about/">Over ons</a>', '<a href="/">Home</a>')


class WebsiteAuditTests(unittest.TestCase):
    def test_known_good_local_pages_produce_no_fabricated_findings(self) -> None:
        report = audit_html_pages({"index.html": GOOD_HTML, "about/index.html": ABOUT_HTML})
        self.assertEqual(report.pages_checked, 2)
        self.assertEqual(report.findings, ())
        self.assertEqual(report.to_dict()["external_requests_made"], 0)
        self.assertFalse(report.to_dict()["live_revenue_or_deliveries"])
        self.assertNotIn("score", report.to_dict())
        self.assertEqual(
            report.content_sha256,
            audit_html_pages({"about/index.html": ABOUT_HTML, "index.html": GOOD_HTML}).content_sha256,
        )

    def test_structural_and_accessible_name_problems_are_reported(self) -> None:
        html = """<html><head></head><body><img src="x.png">
        <a href="/missing/"></a><a href="javascript:alert('x')">Run</a><h2>Hello</h2></body></html>"""
        result = audit_html_pages({"index.html": html})
        codes = {finding.code for finding in result.findings}
        self.assertTrue({
            "HTML_LANG_MISSING_OR_INVALID", "TITLE_MISSING_OR_DUPLICATE",
            "META_DESCRIPTION_MISSING", "VIEWPORT_MISSING",
            "H1_MISSING_OR_MULTIPLE", "IMAGES_MISSING_ALT",
            "LINK_WITHOUT_ACCESSIBLE_NAME", "BROKEN_LOCAL_HTML_LINK", "UNSAFE_LINK",
        }.issubset(codes))

    def test_relative_links_and_html_entity_decoding(self) -> None:
        root = GOOD_HTML.replace('/about/', "about/")
        about = ABOUT_HTML.replace('href="/"', 'href="../index.html?ref=main&amp;q=1"')
        report = audit_html_pages({"index.html": root, "about/index.html": about})
        self.assertEqual(report.findings, ())

    def test_external_links_are_never_fetched(self) -> None:
        html = GOOD_HTML.replace('href="/about/"', 'href="https://example.invalid/not-real"')
        result = audit_html_pages({"index.html": html})
        self.assertNotIn("BROKEN_LOCAL_HTML_LINK", [f.code for f in result.findings])
        self.assertEqual(result.to_dict()["external_requests_made"], 0)

    def test_encoded_traversal_and_private_file_urls_are_flagged_not_loaded(self) -> None:
        html = GOOD_HTML.replace(
            'href="/about/"',
            'href="/%2e%2e/secrets.html"',
        ).replace('href="mailto:info@example.com"', 'href="file:///etc/passwd"')
        result = audit_html_pages({"index.html": html})
        self.assertEqual(sum(f.code == "UNSAFE_LINK" for f in result.findings), 2)

    def test_non_html_assets_are_not_claimed_to_be_checked(self) -> None:
        html = GOOD_HTML.replace('href="/about/"', 'href="/brochure.pdf"')
        report = audit_html_pages({"index.html": html})
        self.assertNotIn("BROKEN_LOCAL_HTML_LINK", [finding.code for finding in report.findings])

    def test_boundaries_refuse_hostile_pages_and_oversized_payloads(self) -> None:
        bad_names = ["../private.html", "/absolute.html", r"dir\escape.html", "C:/system.html", "./index.html"]
        for path in bad_names:
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    audit_html_pages({path: GOOD_HTML})
        with self.assertRaises(ValueError):
            audit_html_pages({})
        with self.assertRaises(ValueError):
            audit_html_pages({f"{i}.html": GOOD_HTML for i in range(MAX_PAGES + 1)})
        with self.assertRaises(ValueError):
            audit_html_pages({"index.html": "a" * (MAX_PAGE_BYTES + 1)})
        with self.assertRaises(TypeError):
            audit_html_pages({"index.html": b"<html></html>"})

    def test_local_directory_is_bounded_and_html_is_never_executed(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            (folder / "index.html").write_text(GOOD_HTML, encoding="utf-8")
            (folder / "about").mkdir()
            (folder / "about" / "index.html").write_text(ABOUT_HTML, encoding="utf-8")
            (folder / "NOT_READ.txt").write_text("THIS IS NOT HTML", encoding="utf-8")
            before = (folder / "index.html").read_bytes()
            files = load_local_html_pages(folder)
            self.assertEqual(set(files), {"index.html", "about/index.html"})
            report = audit_local_site(folder)
            self.assertEqual(report.pages_checked, 2)
            self.assertEqual(report.findings, ())
            self.assertEqual((folder / "index.html").read_bytes(), before)

    def test_reject_oversized_local_input_before_reading(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            (folder / "index.html").write_bytes(b"x" * (MAX_PAGE_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "size"):
                audit_local_site(folder)

    def test_file_and_folder_symlinks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name) / "root"
            root.mkdir()
            target = Path(name) / "target.html"
            target.write_text(GOOD_HTML, encoding="utf-8")
            try:
                (root / "index.html").symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("OS does not permit test symlinks")
            with self.assertRaises(ValueError):
                audit_local_site(root)
            with self.assertRaises(ValueError):
                audit_local_site(root / "index.html")
            (root / "index.html").unlink()
            (root / "index.html").write_text(GOOD_HTML, encoding="utf-8")
            (root / "outside").symlink_to(Path(name), target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symbolic-link directory"):
                audit_local_site(root)

    def test_one_command_cli_exports_json_and_never_overwrites_existing_report(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name) / "site"
            root.mkdir()
            (root / "index.html").write_text(GOOD_HTML.replace('/about/', '/'), encoding="utf-8")
            out = Path(name) / "audit.json"
            env = os.environ.copy()
            env["OPENSHORTS_API_KEY"] = "canary-secret-not-for-audit"
            args = [sys.executable, str(SCRIPT), "--site-dir", str(root), "--output", str(out)]
            first = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(first.returncode, 0, msg=first.stderr)
            self.assertEqual(first.stderr, "")
            result = json.loads(first.stdout)
            self.assertEqual(result["pages_checked"], 1)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), result)
            self.assertNotIn("canary-secret", first.stdout + out.read_text(encoding="utf-8"))
            saved = out.read_bytes()
            second = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(out.read_bytes(), saved)
            self.assertNotIn("canary-secret", second.stderr)


if __name__ == "__main__":
    unittest.main()
