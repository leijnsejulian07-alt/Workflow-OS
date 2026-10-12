"""Shareable, static NL/EN HTML for authorized offline website-audit findings.

Pure formatting only: no script, form, remote assets, tracking, network requests,
sales claims, payments, publishing, or interpretation of raw user HTML.
Every dynamic value (including the page name) is escaped before interpolation.
"""
from __future__ import annotations

import html
from collections import Counter

from .website_audit import WebsiteAuditReport


_MESSAGES: dict[str, dict[str, tuple[str, str]]] = {
    "HTML_LANG_MISSING_OR_INVALID": {
        "en": ("Document language", "Set a valid language on the html element, e.g. lang=\"en\"."),
        "nl": ("Paginataal", "Voeg een geldige taal toe aan het html-element, bijvoorbeeld lang=\"nl\"."),
    },
    "TITLE_MISSING_OR_DUPLICATE": {
        "en": ("Page title", "Provide exactly one meaningful, non-empty title element."),
        "nl": ("Paginatitel", "Voeg precies één duidelijke, niet-lege title-tag toe."),
    },
    "META_DESCRIPTION_MISSING": {
        "en": ("Meta description", "Add a relevant, non-empty meta description."),
        "nl": ("Metabeschrijving", "Voeg een relevante, niet-lege metabeschrijving toe."),
    },
    "VIEWPORT_MISSING": {
        "en": ("Mobile viewport", "Add a meaningful viewport meta tag for mobile presentation."),
        "nl": ("Mobiele weergave", "Voeg een zinvolle viewport-metatag toe voor mobiele apparaten."),
    },
    "H1_MISSING_OR_MULTIPLE": {
        "en": ("Main heading", "Use one meaningful, non-empty h1 heading per page."),
        "nl": ("Hoofdkop", "Gebruik één duidelijke, niet-lege h1-kop per pagina."),
    },
    "IMAGES_MISSING_ALT": {
        "en": ("Image descriptions", "Give informative images descriptive alt text; decorative images may use alt=\"\"."),
        "nl": ("Afbeeldingsbeschrijvingen", "Geef informatieve afbeeldingen alt-tekst; decoratieve afbeeldingen mogen alt=\"\" gebruiken."),
    },
    "LINK_WITHOUT_ACCESSIBLE_NAME": {
        "en": ("Link name", "Provide informative link text or a suitable accessible label."),
        "nl": ("Linknaam", "Geef links herkenbare tekst of een passend toegankelijk label."),
    },
    "UNSAFE_LINK": {
        "en": ("Unsafe link", "Review the link target; remove unsafe or malformed addresses."),
        "nl": ("Onveilig linkadres", "Controleer het linkdoel en verwijder onveilige of ongeldige adressen."),
    },
    "BROKEN_LOCAL_HTML_LINK": {
        "en": ("Broken internal HTML link", "Check the local HTML destination within the provided site files."),
        "nl": ("Kapotte interne HTML-link", "Controleer de bestemming binnen de aangeleverde HTML-bestanden."),
    },
}

_COPY = {
    "en": {
        "title": "Website structure audit",
        "subtitle": "Offline analysis of supplied HTML files",
        "status": "Informational technical report",
        "pages": "Pages reviewed",
        "findings": "Findings",
        "errors": "Errors",
        "warnings": "Warnings",
        "info": "Notes",
        "overview": "Findings by page",
        "none": "No findings from this limited ruleset; this does not certify the website.",
        "rule": "Check",
        "page": "Page",
        "fix": "Suggested next step",
        "limitations": "Scope and important limitations",
        "disclaimer": (
            "This report is based only on supplied local HTML. It did not load the live website, "
            "run JavaScript, measure speed, perform a full accessibility or SEO audit, "
            "or confirm legal compliance. Findings may be incomplete or require expert review. "
            "No score, performance guarantee, certification, sale or payout is implied."
        ),
        "digest": "Source fingerprint",
        "version": "Audit ruleset",
    },
    "nl": {
        "title": "Website-structuuraudit",
        "subtitle": "Offline analyse van aangeleverde HTML-bestanden",
        "status": "Technisch rapport ter informatie",
        "pages": "Gecontroleerde pagina's",
        "findings": "Bevindingen",
        "errors": "Fouten",
        "warnings": "Waarschuwingen",
        "info": "Opmerkingen",
        "overview": "Bevindingen per pagina",
        "none": "Geen bevindingen met deze beperkte controles; dit certificeert de website niet.",
        "rule": "Controle",
        "page": "Pagina",
        "fix": "Voorgestelde vervolgstap",
        "limitations": "Reikwijdte en belangrijke beperkingen",
        "disclaimer": (
            "Dit rapport gebruikt uitsluitend aangeleverde lokale HTML. Het heeft geen live website "
            "bezocht, JavaScript uitgevoerd, snelheid gemeten of een volledige toegankelijkheids-, "
            "SEO- of juridische controle gedaan. Bevindingen zijn mogelijk onvolledig en kunnen "
            "deskundig onderzoek vereisen. Er wordt geen score, keurmerk, verkoop of uitbetaling geclaimd."
        ),
        "digest": "Inhoudscontrolegetal",
        "version": "Versie van de controles",
    },
}
_CSS = """
:root{color-scheme:light;--ink:#10233c;--muted:#52667b;--accent:#d97632;--paper:#f7f9fc;--line:#dce3ea}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 system-ui,sans-serif}
.wrap{max-width:940px;margin:auto;padding:clamp(20px,5vw,58px)}
header{background:var(--ink);color:white;padding:38px 40px;border-radius:18px}
h1{font-size:clamp(1.7rem,4vw,2.6rem);line-height:1.15;margin:0 0 10px}
h2{font-size:1.3rem;margin:35px 0 16px}p{margin:0 0 12px}.intro{opacity:.9}
.kicker{font-size:.75rem;letter-spacing:.11em;text-transform:uppercase;font-weight:700;color:#ffd7b3}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px;margin-top:20px}
.metric,.finding,.disclaimer{background:white;border:1px solid var(--line);border-radius:13px;padding:18px}
.metric b{display:block;font-size:1.7rem;line-height:1.1}.metric span{color:var(--muted);font-size:.87rem}
.finding{margin-bottom:12px;border-left:4px solid var(--accent)}
.finding.error{border-left-color:#b42318}.finding.info{border-left-color:#447aa7}
.finding h3{font-size:1.04rem;margin:0 0 6px}
.small{color:var(--muted);font-size:.86rem;overflow-wrap:anywhere}
.code{font:0.81rem/1.4 ui-monospace,monospace;overflow-wrap:anywhere}
.disclaimer{background:#fff8f0;border-color:#eed7c5}.status{margin-top:8px;font-size:.92rem}
@media print{body{background:white}.wrap{padding:0}.metric,.finding,.disclaimer{break-inside:avoid}}
"""


def render_website_audit_html(report: WebsiteAuditReport, *, language: str = "nl") -> str:
    """Render a deterministic, entirely self-contained HTML report.

    Informational only: no scripts or external resources. This does not
    upgrade any report to a verified commercial delivery or accessibility seal.
    """
    if not isinstance(report, WebsiteAuditReport):
        raise TypeError("report must be WebsiteAuditReport")
    if language not in _COPY:
        raise ValueError("language must be 'nl' or 'en'")
    if len(report.findings) > 500:
        raise ValueError("report has too many findings to format safely")
    labels = _COPY[language]
    safe = lambda value: html.escape(str(value), quote=True)
    counts = Counter(finding.severity for finding in report.findings)
    cards = [
        (labels["pages"], report.pages_checked),
        (labels["findings"], len(report.findings)),
        (labels["warnings"], counts["warning"]),
        (labels["errors"], counts["error"]),
    ]
    metrics = "".join(
        f'<div class="metric"><b>{safe(value)}</b><span>{safe(label)}</span></div>'
        for label, value in cards
    )
    findings = []
    for item in report.findings:
        name, fix = _MESSAGES.get(item.code, {}).get(
            language, (item.code, item.description)
        )
        # Unknown severities cannot become untrusted CSS class names.
        severity = item.severity if item.severity in {"error", "warning", "info"} else "info"
        findings.append(
            f'<article class="finding {severity}">'
            f'<div class="small">{safe(labels["page"])}: {safe(item.page)}'
            f' · {safe(item.severity)}</div>'
            f'<h3>{safe(name)}</h3>'
            f'<p class="code">{safe(item.code)}</p>'
            f'<p><strong>{safe(labels["fix"])}:</strong> {safe(fix)}</p>'
            "</article>"
        )
    body = "".join(findings) if findings else f'<p class="disclaimer">{safe(labels["none"])}</p>'
    output = (
        '<!doctype html>\n'
        f'<html lang="{safe(language)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta name="robots" content="noindex,nofollow">'
        f'<title>{safe(labels["title"])}</title>'
        f'<style>{_CSS}</style></head><body><main class="wrap">'
        '<header>'
        f'<p class="kicker">{safe(labels["status"])}</p>'
        f'<h1>{safe(labels["title"])}</h1>'
        f'<p class="intro">{safe(labels["subtitle"])}</p></header>'
        f'<section class="grid" aria-label="{safe(labels["findings"])}">{metrics}</section>'
        f'<section aria-label="{safe(labels["overview"])}"><h2>{safe(labels["overview"])}</h2>{body}</section>'
        '<section class="disclaimer">'
        f'<h2>{safe(labels["limitations"])}</h2>'
        f'<p>{safe(labels["disclaimer"])}</p>'
        f'<p class="small"><strong>{safe(labels["version"])}:</strong> {safe(report.ruleset_version)}'
        f' · <strong>{safe(labels["digest"])}:</strong> {safe(report.content_sha256)}</p>'
        '</section></main></body></html>\n'
    )
    if len(output.encode("utf-8")) > 1_000_000:
        raise ValueError("HTML report exceeds 1 MiB safety limit")
    return output
