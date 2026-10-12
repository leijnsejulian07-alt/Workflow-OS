"""Bounded, deterministic, OFFLINE HTML audit for a future website-audit product.

This is a limited static check (structure, basic metadata, links, images), NOT
a Lighthouse run, accessibility certification, SEO ranking or paid customer job.
No HTTP fetches, browser, JavaScript execution, publishing or payment authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Mapping
from urllib.parse import unquote, urlsplit

RULESET_VERSION = "offline-html-v1"
MAX_PAGES = 25
MAX_PAGE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024
MAX_DIRECTORIES = 250
_ALLOWED_SUFFIXES = {".htm", ".html"}
_PATH_PATTERN = re.compile(r"^[^\x00-\x1f\x7f\\]+$")


@dataclass(frozen=True)
class AuditFinding:
    page: str
    code: str
    severity: str
    description: str


@dataclass(frozen=True)
class WebsiteAuditReport:
    ruleset_version: str
    scan_mode: str
    pages_checked: int
    content_sha256: str
    findings: tuple[AuditFinding, ...]
    limitation: str = "Static offline heuristics only; not an accessibility/SEO certification."

    def to_dict(self) -> dict[str, object]:
        severity_counts = {
            level: sum(f.severity == level for f in self.findings)
            for level in ("error", "warning", "info")
        }
        return {
            "ruleset_version": self.ruleset_version,
            "scan_mode": self.scan_mode,
            "pages_checked": self.pages_checked,
            "content_sha256": self.content_sha256,
            "severity_counts": severity_counts,
            "findings": [asdict(f) for f in self.findings],
            "limitation": self.limitation,
            "external_requests_made": 0,
            "live_revenue_or_deliveries": False,
        }


class _HTMLInspector(HTMLParser):
    """Extract limited structural evidence, never executing untrusted markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.language = ""
        self.titles: list[str] = []
        self._in_title = False
        self._current_title = ""
        self.h1_count = 0
        self._in_h1 = 0
        self._current_h1 = ""
        self.h1_texts: list[str] = []
        self.meta_description = ""
        self.viewport = False
        self.images_without_alt = 0
        self.links: list[tuple[str, str]] = []
        self._active_anchor: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = {key.lower(): (value or "") for key, value in attrs}
        if tag == "html":
            self.language = attributes.get("lang", "").strip()
        elif tag == "title":
            self._in_title = True
            self._current_title = ""
        elif tag == "h1":
            self.h1_count += 1
            self._in_h1 += 1
            self._current_h1 = ""
        elif tag == "meta":
            name = attributes.get("name", "").strip().lower()
            if name == "description":
                self.meta_description = attributes.get("content", "").strip()
            if name == "viewport":
                self.viewport = bool(attributes.get("content", "").strip())
        elif tag == "img":
            if "alt" not in attributes:
                self.images_without_alt += 1
            if self._active_anchor is not None:
                self._active_anchor["label"] += " " + attributes.get("alt", "")
        elif tag == "a":
            if self._active_anchor is not None:
                self.links.append((
                    self._active_anchor["href"], self._active_anchor["label"].strip()
                ))
            self._active_anchor = {
                "href": attributes.get("href", "").strip(),
                "label": (
                    attributes.get("aria-label", "").strip()
                    or attributes.get("title", "").strip()
                ),
            }

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in {"img", "meta", "br", "hr", "input", "source", "link"}:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._current_title += data
        if self._in_h1:
            self._current_h1 += data
        if self._active_anchor is not None:
            self._active_anchor["label"] += data

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title" and self._in_title:
            self.titles.append(self._current_title.strip())
            self._in_title = False
        elif tag == "h1" and self._in_h1:
            self.h1_texts.append(self._current_h1.strip())
            self._in_h1 -= 1
        elif tag == "a" and self._active_anchor is not None:
            self.links.append((
                self._active_anchor["href"], self._active_anchor["label"].strip()
            ))
            self._active_anchor = None

    def close(self) -> None:
        super().close()
        if self._active_anchor is not None:
            self.links.append((
                self._active_anchor["href"], self._active_anchor["label"].strip()
            ))
            self._active_anchor = None
        if self._in_title:
            self.titles.append(self._current_title.strip())
            self._in_title = False


def _validated_name(name: object) -> str:
    if not isinstance(name, str) or not name or len(name) > 500:
        raise ValueError("HTML page name is missing or oversized")
    if not _PATH_PATTERN.fullmatch(name) or name.startswith("/") or ":" in name:
        raise ValueError("HTML page name is unsafe")
    if "//" in name or name.endswith("/") or any(part in {"", ".", ".."} for part in name.split("/")):
        raise ValueError("HTML page name must be a normalized relative file path")
    if PurePosixPath(name).suffix.lower() not in _ALLOWED_SUFFIXES:
        raise ValueError("only .html/.htm pages may be audited")
    return name


def _local_target(page: str, href: str) -> tuple[str | None, bool]:
    """Return a normalized HTML page target and whether the URI is unsafe."""
    if not href or href.startswith("#"):
        return None, False
    if len(href) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in href):
        return None, True
    if href.startswith("//"):
        return None, False  # external; never fetched
    try:
        parts = urlsplit(href)
    except ValueError:
        return None, True
    if parts.scheme:
        return None, parts.scheme.lower() not in {"https", "http", "mailto", "tel"}
    if parts.netloc:
        return None, True
    path = unquote(parts.path)
    if not path:
        return None, False
    if "\\" in path or "\x00" in path:
        return None, True
    base = "" if path.startswith("/") else posixpath.dirname(page)
    relative = posixpath.normpath(posixpath.join(base, path.lstrip("/")))
    if relative.startswith("../") or relative == ".." or relative.startswith("/"):
        return None, True
    if path.endswith("/") or relative in {".", ""}:
        relative = posixpath.join(relative if relative != "." else "", "index.html")
    elif not posixpath.splitext(relative)[1]:
        relative = posixpath.join(relative, "index.html")
    if PurePosixPath(relative).suffix.lower() not in _ALLOWED_SUFFIXES:
        return None, False  # other local assets are deliberately out of audit scope
    return relative, False


def audit_html_pages(pages: Mapping[str, str]) -> WebsiteAuditReport:
    """Analyze caller-owned HTML, with strict limits and no external I/O."""
    if not isinstance(pages, Mapping) or not 1 <= len(pages) <= MAX_PAGES:
        raise ValueError("site must contain between 1 and 25 HTML pages")
    normalized: dict[str, str] = {}
    total = 0
    for raw_name, source in pages.items():
        name = _validated_name(raw_name)
        if not isinstance(source, str):
            raise TypeError("HTML document content must be text")
        encoded = source.encode("utf-8")
        if not encoded or len(encoded) > MAX_PAGE_BYTES:
            raise ValueError("HTML document has invalid size")
        total += len(encoded)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("site exceeds maximum audit size")
        if name in normalized:
            raise ValueError("duplicate HTML page")
        normalized[name] = source

    results: list[AuditFinding] = []
    digest = hashlib.sha256()
    for name in sorted(normalized):
        encoded = normalized[name].encode("utf-8")
        digest.update(name.encode("utf-8") + b"\x00")
        digest.update(hashlib.sha256(encoded).digest())
        inspector = _HTMLInspector()
        inspector.feed(normalized[name])
        inspector.close()

        def issue(code: str, severity: str, description: str) -> None:
            results.append(AuditFinding(name, code, severity, description))

        if not inspector.language or not re.fullmatch(r"[a-zA-Z]{2}(?:-[a-zA-Z]{2})?", inspector.language):
            issue("HTML_LANG_MISSING_OR_INVALID", "warning", "Document language is missing or malformed.")
        if len(inspector.titles) != 1 or not inspector.titles[0]:
            issue("TITLE_MISSING_OR_DUPLICATE", "warning", "A single non-empty page title was not found.")
        if not inspector.meta_description:
            issue("META_DESCRIPTION_MISSING", "info", "A non-empty meta description was not found.")
        if not inspector.viewport:
            issue("VIEWPORT_MISSING", "warning", "Responsive viewport metadata was not found.")
        if inspector.h1_count != 1 or not any(inspector.h1_texts):
            issue("H1_MISSING_OR_MULTIPLE", "warning", "A single non-empty h1 heading was not found.")
        if inspector.images_without_alt:
            issue("IMAGES_MISSING_ALT", "warning", f"{inspector.images_without_alt} image(s) lack an alt attribute.")
        for href, label in inspector.links:
            if not label:
                issue("LINK_WITHOUT_ACCESSIBLE_NAME", "warning", "Link text or an accessible name was not found.")
            target, unsafe = _local_target(name, href)
            if unsafe:
                issue("UNSAFE_LINK", "warning", "Link has an unsafe or malformed target.")
            elif target is not None and target not in normalized:
                issue("BROKEN_LOCAL_HTML_LINK", "warning", "Local HTML link target is not in the provided pages.")

    results.sort(key=lambda finding: (finding.page, finding.code, finding.description))
    return WebsiteAuditReport(
        ruleset_version=RULESET_VERSION,
        scan_mode="LOCAL_HTML_ONLY",
        pages_checked=len(normalized),
        content_sha256=digest.hexdigest(),
        findings=tuple(results),
    )


def load_local_html_pages(root: Path) -> dict[str, str]:
    """Read a bounded local tree. Reject symlinks and never fetch remote URLs."""
    folder = Path(root).expanduser()
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("site directory is missing or is a symlink")
    folder = folder.resolve(strict=True)
    pages: dict[str, str] = {}
    total = 0
    visited = 0
    for current, directories, filenames in os.walk(folder, followlinks=False):
        visited += 1
        if visited > MAX_DIRECTORIES:
            raise ValueError("site directory traversal limit exceeded")
        for directory in directories:
            if (Path(current) / directory).is_symlink():
                raise ValueError("site contains a symbolic-link directory")
        for filename in filenames:
            path = Path(current) / filename
            if path.suffix.lower() not in _ALLOWED_SUFFIXES:
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError("HTML file is not an ordinary file")
            relative = path.relative_to(folder).as_posix()
            relative = _validated_name(relative)
            if len(pages) >= MAX_PAGES:
                raise ValueError("site page count exceeds limit")
            size = path.stat().st_size
            if size <= 0 or size > MAX_PAGE_BYTES or total + size > MAX_TOTAL_BYTES:
                raise ValueError("HTML file or site exceeds audit size bounds")
            # An already verified local file: do not execute HTML or follow links.
            content = path.read_bytes()
            if len(content) != size:
                raise ValueError("HTML file changed while being read")
            try:
                pages[relative] = content.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ValueError("HTML file is not UTF-8") from exc
            total += len(content)
    if not pages:
        raise ValueError("no HTML files were found in the supplied directory")
    return pages


def audit_local_site(folder: Path) -> WebsiteAuditReport:
    """Pure offline audit of a user-authorized local HTML directory."""
    return audit_html_pages(load_local_html_pages(folder))
