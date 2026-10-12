# Website Audit Factory — offline HTML pilot

> **Language:** English · [Nederlands](WEBSITE_AUDIT.nl.md)
>
> **Implementation status:** local code and CLI exist in this branch. This is not a paid product, a live site crawler, an accessibility certification, a full SEO audit, or proof of conversion/sales.

## Purpose and reusable components

The new, **dependency-free** `src/workflow_os/website_audit.py` module performs deterministic checks on **customer-owned or otherwise authorized, already-available HTML source files**. It does **not** fetch URLs, connect to external accounts, execute JavaScript, deploy sites, send sales messages, start subscriptions or request payment.

- `audit_html_pages({"index.html": "<html>...</html>"})` can consume an in-memory collection, including HTML from the existing Website-in-a-Box builder. It is a **separate advisory check**; it does not bypass `qa_static_site`, the payment gate, rights ledger, customer approvals or deployment gates.
- `audit_local_site(Path("folder"))` loads bounded HTML from a local directory while refusing symlinks and oversized inputs.
- `scripts/run_website_audit.py` is a standalone read-only audit CLI. It emits deterministic JSON and can create new JSON and HTML output files with no-overwrite semantics.
- `src/workflow_os/website_audit_report.py` renders shareable, responsive, self-contained **Dutch or English HTML**. Dynamic data is HTML-escaped, scripts/tracking/remote assets are absent, and output is bounded to 1 MiB / 500 findings.
- `tests/test_website_audit.py` exercises good and problematic sites, missing HTML metadata, link safety, input limits, symlinks and CLI isolation.
- `tests/test_website_audit_report.py` checks NL/EN presentation, no false certification, HTML injection safety and create-only export behavior.

## One-command demo

From a Python 3.12+ checkout of Workflow OS, with files you have the right to inspect:

```powershell
python scripts/run_website_audit.py --site-dir "C:\my-authorized-static-site" --output "C:\reports\audit.json" --output-html "C:\reports\audit-nl.html" --language nl
```

**Input requirements:** an existing local directory with UTF-8 `.html`/`.htm` pages; maximum 25 pages, 256 KiB each and 2 MiB total. Directory traversal is bounded. The output folder must already exist. Reports are created with no-overwrite mode, and an existing report will not be replaced. Relative file names and a digest support reproducibility.

The JSON report contains a ruleset version, the number of pages, content SHA-256, severity counts and findings. The optional self-contained HTML report is a client-readable **advisory document**, not a quality certificate; choose `--language en` for English. Both output files must not exist before the run. The number of findings is limited to 500. No external services are contacted. A successful audit command **does not mean that a page passes accessibility, SEO, privacy or performance requirements**. Findings are **heuristics** and require human review before they are used as paid marketing claims.

## Current static checks

- Present/non-empty `<title>`, HTML language, basic meta description and mobile viewport.
- A single non-empty `<h1>` heading.
- `<img>` elements without an `alt` attribute; an empty `alt=""` is permitted for decorative imagery.
- Links without a detectable text/ARIA-label/title/image-alt name (a conservative heuristic).
- Broken links **to HTML files included in the local input set**, and obviously unsafe local link targets.

**Explicit exclusions:** no remote site fetching or URL list crawling, no CSS/JS execution, no JavaScript-rendered content checks, no runtime performance metrics, no full WCAG/SEO certification, no forms/checkout tests, no external links verification, no screenshot comparison, no legal/privacy compliance opinion and no scoring of profitability. Some accessible names and dynamic links may not be recognized by this simple parser.

## Pilot graduation gates (not yet performed)

1. Add tests for an authorized, representative collection of static sites, manually review false positives/negatives and record rule versions.
2. If useful, consider a **separately sandboxed** Lighthouse/axe-core adapter **after** browser/runtime/security/license/CPU benchmarking. Never add Chrome or a Node stack blindly to the weak Windows test device.
3. Validate demand by showing opt-in, truthfully labeled sample reports to potential customers; no unsolicited bulk outreach, scraped customer data or false certifications.
4. Only after a customer-approved commercial scope and checkout/payment system is independently authorized: implement a self-service sale → generation → verified delivery → refund/support workflow, testing simulation first.
5. Track actual paid receipts and full marginal costs; do not count sample audits as revenue.

This pilot has **no account integration, outbound network path, payment collection or autonomy to publish**.
