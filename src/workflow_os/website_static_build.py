"""Deterministic, bounded static build + QA for Website-in-a-Box.

This module deliberately avoids a Node/runtime dependency for the first executable
slice. Customer content is treated as hostile plain text, escaped into a tiny
self-contained static site, and never interpreted as HTML, shell input, paths, or
remote-fetch instructions. The output is an in-memory artifact; deployment and
hosting side effects remain separate concerns.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import json
import re
from typing import Any
from urllib.parse import urlparse

from .website_fulfillment_gate import FulfillmentGateDecision, WebsiteScopeSnapshot

_MAX_TOTAL_BYTES = 1_000_000
_MAX_FILE_BYTES = 256_000
_MAX_TEXT = 20_000
_SLUG_RE = re.compile(r"^(?:index|[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class StaticPageInput:
    slug: str
    title: str
    body: str


@dataclass(frozen=True)
class WebsiteContentSpec:
    site_title: str
    description: str
    pages: tuple[StaticPageInput, ...]
    contact_label: str
    contact_href: str
    language: str = "nl"


@dataclass(frozen=True)
class BuiltStaticFile:
    path: str
    content: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class WebsiteBuildArtifact:
    opportunity_id: str
    scope_sha256: str
    files: tuple[BuiltStaticFile, ...]
    manifest_sha256: str
    total_bytes: int


@dataclass(frozen=True)
class WebsiteQADecision:
    state: str
    reason: str
    opportunity_id: str
    manifest_sha256: str


def _text(value: Any, field: str, *, max_length: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    text = value.strip()
    if not text or len(text) > max_length:
        raise ValueError(f"{field} is missing or too long")
    return text


def _slug(value: Any) -> str:
    slug = _text(value, "slug", max_length=64).lower()
    if not _SLUG_RE.fullmatch(slug):
        raise ValueError("page slug is unsafe")
    return slug


def _contact_href(value: Any) -> str:
    href = _text(value, "contact_href", max_length=512)
    parsed = urlparse(href)
    # The first bounded product supports only direct mail/phone CTA. This avoids
    # hidden trackers, remote dependencies, javascript URLs, and SSRF-like fetches.
    if parsed.scheme not in {"mailto", "tel"}:
        raise ValueError("contact href must use mailto: or tel:")
    if parsed.netloc:
        raise ValueError("contact href must not contain a network location")
    return href


def _escape_paragraphs(body: str) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
    if not paragraphs:
        raise ValueError("page body is empty")
    return "".join(f"<p>{html.escape(part)}</p>" for part in paragraphs)


def _path_for_slug(slug: str) -> str:
    return "index.html" if slug == "index" else f"{slug}/index.html"


def _href_for_slug(slug: str) -> str:
    return "/" if slug == "index" else f"/{slug}/"


def _render_page(spec: WebsiteContentSpec, page: StaticPageInput) -> str:
    nav = "".join(
        f'<a href="{html.escape(_href_for_slug(other.slug), quote=True)}">{html.escape(other.title)}</a>'
        for other in spec.pages
    )
    return (
        "<!doctype html>\n"
        f'<html lang="{html.escape(spec.language, quote=True)}">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{html.escape(page.title)} | {html.escape(spec.site_title)}</title>\n"
        f'<meta name="description" content="{html.escape(spec.description, quote=True)}">\n'
        "<style>body{font-family:system-ui,sans-serif;max-width:72rem;margin:auto;padding:1.25rem;line-height:1.6}"
        "nav{display:flex;gap:1rem;flex-wrap:wrap}main{margin-top:2rem}.cta{display:inline-block;padding:.65rem 1rem;border:1px solid currentColor;border-radius:.5rem}</style>\n"
        "</head>\n<body>\n"
        f'<nav aria-label="Hoofdnavigatie">{nav}</nav>\n'
        f"<main><h1>{html.escape(page.title)}</h1>{_escape_paragraphs(page.body)}"
        f'<p><a class="cta" href="{html.escape(spec.contact_href, quote=True)}">{html.escape(spec.contact_label)}</a></p>'
        "</main>\n</body>\n</html>\n"
    )


def build_static_site(
    snapshot: WebsiteScopeSnapshot,
    gate: FulfillmentGateDecision,
    content: WebsiteContentSpec,
) -> WebsiteBuildArtifact:
    """Build a self-contained in-memory static artifact after the payment gate.

    This function performs no network, filesystem, deployment, shell, or payment
    side effect. It is deterministic for the same immutable scope + content.
    """
    if not isinstance(snapshot, WebsiteScopeSnapshot):
        raise TypeError("snapshot must be WebsiteScopeSnapshot")
    if not isinstance(gate, FulfillmentGateDecision):
        raise TypeError("gate must be FulfillmentGateDecision")
    if gate.state != "READY_FOR_BOUNDED_BUILD":
        raise ValueError("payment gate is not ready for bounded build")
    if gate.opportunity_id != snapshot.opportunity_id or gate.scope_sha256 != snapshot.snapshot_sha256:
        raise ValueError("fulfillment gate identity mismatch")
    if not isinstance(content, WebsiteContentSpec):
        raise TypeError("content must be WebsiteContentSpec")

    _text(content.site_title, "site_title", max_length=160)
    _text(content.description, "description", max_length=320)
    _text(content.contact_label, "contact_label", max_length=120)
    _contact_href(content.contact_href)
    language = _text(content.language, "language", max_length=16).lower()
    if not re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", language):
        raise ValueError("language is malformed")

    if len(content.pages) != snapshot.pages:
        raise ValueError("content page count does not match immutable scope")
    if not 1 <= len(content.pages) <= 5:
        raise ValueError("content page count exceeds bounded product")

    seen: set[str] = set()
    normalized_pages: list[StaticPageInput] = []
    for raw in content.pages:
        if not isinstance(raw, StaticPageInput):
            raise TypeError("pages must contain StaticPageInput values")
        slug = _slug(raw.slug)
        if slug in seen:
            raise ValueError("duplicate page slug")
        seen.add(slug)
        normalized_pages.append(
            StaticPageInput(slug=slug, title=_text(raw.title, "page title", max_length=160), body=_text(raw.body, "page body"))
        )
    if "index" not in seen:
        raise ValueError("static site requires an index page")

    normalized = WebsiteContentSpec(
        site_title=content.site_title.strip(),
        description=content.description.strip(),
        pages=tuple(normalized_pages),
        contact_label=content.contact_label.strip(),
        contact_href=content.contact_href.strip(),
        language=language,
    )

    files: list[BuiltStaticFile] = []
    total = 0
    for page in normalized.pages:
        rendered = _render_page(normalized, page)
        encoded = rendered.encode("utf-8")
        if len(encoded) > _MAX_FILE_BYTES:
            raise ValueError("generated page exceeds per-file size limit")
        total += len(encoded)
        if total > _MAX_TOTAL_BYTES:
            raise ValueError("generated site exceeds total size limit")
        files.append(BuiltStaticFile(_path_for_slug(page.slug), rendered, hashlib.sha256(encoded).hexdigest(), len(encoded)))

    manifest_payload = {
        "opportunity_id": snapshot.opportunity_id,
        "scope_sha256": snapshot.snapshot_sha256,
        "files": [{"path": f.path, "sha256": f.sha256, "size_bytes": f.size_bytes} for f in files],
    }
    canonical = json.dumps(manifest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return WebsiteBuildArtifact(
        opportunity_id=snapshot.opportunity_id,
        scope_sha256=snapshot.snapshot_sha256,
        files=tuple(files),
        manifest_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        total_bytes=total,
    )


def qa_static_site(snapshot: WebsiteScopeSnapshot, artifact: WebsiteBuildArtifact) -> WebsiteQADecision:
    """Fail closed unless the generated artifact is safe for later handoff."""
    if artifact.opportunity_id != snapshot.opportunity_id or artifact.scope_sha256 != snapshot.snapshot_sha256:
        raise ValueError("artifact identity mismatch")
    if not _SHA256_RE.fullmatch(artifact.manifest_sha256):
        raise ValueError("artifact manifest digest is malformed")
    if len(artifact.files) != snapshot.pages or not artifact.files:
        return WebsiteQADecision("HOLD", "ARTIFACT_PAGE_COUNT_MISMATCH", snapshot.opportunity_id, artifact.manifest_sha256)
    if artifact.total_bytes <= 0 or artifact.total_bytes > _MAX_TOTAL_BYTES:
        return WebsiteQADecision("HOLD", "ARTIFACT_TOTAL_SIZE_INVALID", snapshot.opportunity_id, artifact.manifest_sha256)

    paths = {file.path for file in artifact.files}
    if len(paths) != len(artifact.files) or "index.html" not in paths:
        return WebsiteQADecision("HOLD", "ARTIFACT_PATH_SET_INVALID", snapshot.opportunity_id, artifact.manifest_sha256)

    linked_paths: set[str] = set()
    total = 0
    for file in artifact.files:
        if file.path.startswith(("/", "\\")) or ".." in file.path.split("/") or not file.path.endswith("index.html"):
            return WebsiteQADecision("HOLD", "UNSAFE_ARTIFACT_PATH", snapshot.opportunity_id, artifact.manifest_sha256)
        encoded = file.content.encode("utf-8")
        total += len(encoded)
        if len(encoded) != file.size_bytes or len(encoded) > _MAX_FILE_BYTES:
            return WebsiteQADecision("HOLD", "ARTIFACT_SIZE_MISMATCH", snapshot.opportunity_id, artifact.manifest_sha256)
        if hashlib.sha256(encoded).hexdigest() != file.sha256:
            return WebsiteQADecision("HOLD", "ARTIFACT_DIGEST_MISMATCH", snapshot.opportunity_id, artifact.manifest_sha256)

        lower = file.content.lower()
        required = ("<!doctype html>", "<html lang=", '<meta name="viewport"', '<meta name="description"', "<main>", "<h1>")
        if not all(marker in lower for marker in required):
            return WebsiteQADecision("HOLD", "BASIC_HTML_ACCESSIBILITY_OR_SEO_MISSING", snapshot.opportunity_id, artifact.manifest_sha256)
        if "<script" in lower or "javascript:" in lower or "<iframe" in lower or "<form" in lower:
            return WebsiteQADecision("HOLD", "ACTIVE_OR_REMOTE_CONTENT_PROHIBITED", snapshot.opportunity_id, artifact.manifest_sha256)
        if re.search(r"(?:src|href)\s*=\s*[\"']https?://", file.content, flags=re.IGNORECASE):
            return WebsiteQADecision("HOLD", "REMOTE_DEPENDENCY_PROHIBITED", snapshot.opportunity_id, artifact.manifest_sha256)

        for href in re.findall(r'href="([^"]+)"', file.content, flags=re.IGNORECASE):
            if href.startswith("mailto:") or href.startswith("tel:"):
                continue
            if not href.startswith("/"):
                return WebsiteQADecision("HOLD", "UNSAFE_LINK_TARGET", snapshot.opportunity_id, artifact.manifest_sha256)
            target = "index.html" if href == "/" else f"{href.strip('/')}/index.html"
            linked_paths.add(target)

    if total != artifact.total_bytes:
        return WebsiteQADecision("HOLD", "ARTIFACT_TOTAL_SIZE_MISMATCH", snapshot.opportunity_id, artifact.manifest_sha256)
    if not linked_paths.issubset(paths):
        return WebsiteQADecision("HOLD", "BROKEN_INTERNAL_LINK", snapshot.opportunity_id, artifact.manifest_sha256)

    return WebsiteQADecision("PASS_FOR_HANDOFF_RESERVATION", "STATIC_BUILD_QA_PASSED_NO_DEPLOYMENT_PERFORMED", snapshot.opportunity_id, artifact.manifest_sha256)
