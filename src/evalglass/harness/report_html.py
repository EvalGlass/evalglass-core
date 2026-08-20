"""Diagnostic-first HTML dashboard renderer (Epic E / E2; ADR 0060).

Renders the default ``report.html`` by injecting the typed, score-neutral dashboard projection
(``evalglass.dashboard/1`` — built by :func:`evalglass.harness.dashboard.project_run`) into the
packaged, self-contained template under ``reporting/``. Like the Markdown sink it **computes no**
score, verdict, authority, gate, or delta: every fact comes from the projection, which copies them
from the typed ``Scorecard``/``RunRecord``.

The output is one self-contained HTML file — inline CSS/JS, a ``data:`` favicon, the projection
embedded as JSON with ``<`` escaped, a restrictive Content-Security-Policy, and no external
script/style/font/image/network dependency — so it works from ``file://``. The previous per-metric
renderer stays available for one compatibility release in ``report_html_legacy`` (opt in with
``EVALGLASS_HTML_RENDERER=legacy``).
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

#: The packaged template assets (vendored verbatim into a host by the installer, EG-DX-E2).
_REPORTING = Path(__file__).with_name("reporting")
_SHELL = "dashboard_shell.html"
_CSS = "dashboard.css"
_JS = "dashboard.js"
_STYLE_MARKER = "<!-- EVALGLASS:STYLE -->"
_DATA_MARKER = "<!-- EVALGLASS:DATA -->"
_SCRIPT_MARKER = "<!-- EVALGLASS:SCRIPT -->"
_CSP_MARKER = "<!-- EVALGLASS:CSP -->"


def _asset(name: str) -> str:
    return (_REPORTING / name).read_text(encoding="utf-8")


def _sha256_source(content: str) -> str:
    """A CSP ``'sha256-...'`` source pinning exactly this inline block (no ``unsafe-inline``)."""
    digest = base64.b64encode(hashlib.sha256(content.encode("utf-8")).digest()).decode("ascii")
    return f"'sha256-{digest}'"


def _csp_meta(css: str, javascript: str) -> str:
    """A restrictive CSP that hash-pins the two inline blocks — no network, no ``unsafe-inline``.

    The JSON data island is ``type="application/json"`` (data, never executed), so it needs no
    script-src source; the executable JS and the CSS are pinned by content hash instead.
    """
    csp = (
        "default-src 'none'; img-src data:; "
        f"style-src {_sha256_source(css)}; script-src {_sha256_source(javascript)}; "
        "base-uri 'none'; form-action 'none'"
    )
    return f'<meta http-equiv="Content-Security-Policy" content="{csp}">'


def render_dashboard(projection: Mapping[str, Any]) -> str:
    """Inject the projection + inline CSS/JS into the template, returning one self-contained page.

    The JSON payload is embedded with ``<`` escaped so a hostile ``</script>`` in host data cannot
    break out of the ``<script type="application/json">`` island; all rendering of host strings into
    the DOM is escaped by the template's own ``escapeHtml`` before insertion. The CSP hash-pins the
    two inline blocks, so the report needs no ``unsafe-inline`` and still loads from ``file://``.
    """
    shell = _asset(_SHELL)
    css = _asset(_CSS)
    javascript = _asset(_JS)
    for marker in (_STYLE_MARKER, _DATA_MARKER, _SCRIPT_MARKER, _CSP_MARKER):
        if shell.count(marker) != 1:
            raise ValueError(f"dashboard template must contain exactly one {marker}")
    encoded = json.dumps(projection, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )
    return (
        shell.replace(_CSP_MARKER, _csp_meta(css, javascript))
        .replace(_STYLE_MARKER, f"<style>{css}</style>")
        .replace(_DATA_MARKER, encoded)
        .replace(_SCRIPT_MARKER, f"<script>{javascript}</script>")
    )


class HtmlScoreSink:
    """A ``ScoreSink`` over a prebuilt dashboard projection (the CLI builds it via ``project_run``).

    The projection carries all display facts, so the sink itself neither reaches into a Scorecard
    nor recomputes anything — it only renders. ``render`` ignores its ``scorecard`` argument (kept
    for protocol compatibility) and returns the self-contained HTML for the stored projection.
    """

    def __init__(self, projection: Mapping[str, Any]) -> None:
        self._projection = dict(projection)

    def render(self, scorecard: Any = None) -> str:
        del scorecard  # the projection is the single source of rendered facts
        return render_dashboard(self._projection)
