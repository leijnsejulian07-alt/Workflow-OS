"""Tests for strictly offline NL/EN customer-readable audit report formatting."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from workflow_os.website_audit import (
    AuditFinding, WebsiteAuditReport, audit_html_pages,
)
from workflow_os.website_audit_report import render_website_audit_html


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_website_audit.py"
GOOD = ('<!doctype html><html lang="nl"><head><title>Home</title>'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="description" content="Voorbeeld"></head>'
        '<body><h1>Welkom</h1><a href="/">Home</a></body></html>')


class WebsiteAuditHTMLReportTests(unittest.TestCase):
    def test_bilingual_report_is_deterministic_and_self_contained(self) -> None:
        report = audit_html_pages({"index.html": GOOD.replace("<h1>Welkom</h1>", "<h2>Welkom</h2>")})
        nl = render_website_audit_html(report, language="nl")
        en = render_website_audit_html(report, language="en")
        self.assertIn('<html lang="nl">', nl)
        self.assertIn('<html lang="en">', en)
        self.assertIn("Website-structuuraudit", nl)
        self.assertIn("Website structure audit", en)
        self.assertIn("Hoofdkop", nl)
        self.assertIn("Main heading", en)
        self.assertIn(report.content_sha256, nl)
        self.assertIn('name="robots" content="noindex,nofollow"', en)
        self.assertEqual(nl, render_website_audit_html(report, language="nl"))
        self.assertNotIn("<script", nl.lower())
        self.assertNotIn("<iframe", nl.lower())
        self.assertNotIn("<link", nl.lower())
        self.assertNotIn("href=", nl.lower())
        self.assertIn("geen live website", nl.lower())
        self.assertIn("no score", en.lower())

    def test_no_findings_is_not_a_fake_certification(self) -> None:
        report = audit_html_pages({"index.html": GOOD})
        self.assertEqual(report.findings, ())
        nl = render_website_audit_html(report, language="nl")
        self.assertIn("Geen bevindingen", nl)
        self.assertIn("certificeert de website niet", nl)
        self.assertNotIn("100/100", nl)

    def test_dynamic_names_and_untrusted_descriptions_are_escaped(self) -> None:
        report = WebsiteAuditReport(
            ruleset_version="test-<svg/onload=alert(2)>",
            scan_mode="LOCAL_HTML_ONLY",
            pages_checked=1,
            content_sha256="<script>alert(3)</script>",
            findings=(AuditFinding(
                page='<img src=x onerror="alert(4)">.html',
                code='<script>alert(5)</script>',
                severity='"><script>alert(6)</script>',
                description='<svg onload="alert(7)">',
            ),),
        )
        html = render_website_audit_html(report, language="nl")
        self.assertNotIn('<script>alert', html)
        self.assertNotIn('<img src=x', html)
        self.assertNotIn('<svg ', html)
        self.assertIn('&lt;script&gt;alert(5)&lt;/script&gt;', html)
        self.assertIn('&lt;img src=x', html)
        self.assertNotIn('class="finding ">', html)

    def test_validation_and_bounded_report(self) -> None:
        report = audit_html_pages({"index.html": GOOD})
        with self.assertRaises(ValueError):
            render_website_audit_html(report, language="de")
        with self.assertRaises(TypeError):
            render_website_audit_html({"findings": []})  # type: ignore[arg-type]
        many_anchors = GOOD + '<a href="/"></a>' * 510
        with self.assertRaisesRegex(ValueError, "findings exceed"):
            audit_html_pages({"index.html": many_anchors})

    def test_cli_can_create_nl_html_and_json_once(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            base = Path(dirname)
            site = base / "site"
            site.mkdir()
            (site / "index.html").write_text(GOOD, encoding="utf-8")
            json_out = base / "audit.json"
            html_out = base / "audit.html"
            args = [
                sys.executable, str(SCRIPT), "--site-dir", str(site),
                "--output", str(json_out), "--output-html", str(html_out),
                "--language", "nl",
            ]
            first = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=20)
            self.assertEqual(first.returncode, 0, msg=first.stderr)
            self.assertEqual(first.stderr, "")
            output = json.loads(first.stdout)
            self.assertEqual(json.loads(json_out.read_text(encoding="utf-8")), output)
            report_html = html_out.read_text(encoding="utf-8")
            self.assertTrue(report_html.startswith("<!doctype html>"))
            self.assertIn("Website-structuuraudit", report_html)
            saved_json = json_out.read_bytes()
            saved_html = html_out.read_bytes()
            second = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=20)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(saved_json, json_out.read_bytes())
            self.assertEqual(saved_html, html_out.read_bytes())

    def test_cli_en_report_does_not_require_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            base = Path(dirname)
            site = base / "site"
            site.mkdir()
            (site / "index.html").write_text(GOOD, encoding="utf-8")
            html_out = base / "audit-en.html"
            cp = subprocess.run(
                [sys.executable, str(SCRIPT), "--site-dir", str(site),
                 "--output-html", str(html_out), "--language", "en"],
                cwd=ROOT, capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(cp.returncode, 0, msg=cp.stderr)
            self.assertIn("Website structure audit", html_out.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(cp.stdout)["external_requests_made"], 0)


if __name__ == "__main__":
    unittest.main()
