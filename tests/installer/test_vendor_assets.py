"""EG-DX-E2 — the dashboard template assets vendor into a host so report.html renders."""

from __future__ import annotations

from pathlib import Path

import evalglass
from evalglass.installer.vendor import managed_files, vendor

_FRAMEWORK_PKG = Path(evalglass.__file__).resolve().parent
_ASSETS = (
    "evals/_evalglass/harness/reporting/dashboard_shell.html",
    "evals/_evalglass/harness/reporting/dashboard.css",
    "evals/_evalglass/harness/reporting/dashboard.js",
)


def test_managed_files_include_the_dashboard_template() -> None:
    by_path = {mc.path: mc for mc in managed_files(_FRAMEWORK_PKG, "0.0.0")}
    for asset in _ASSETS:
        assert asset in by_path
        assert by_path[asset].purpose == "harness"
        assert by_path[asset].content  # copied verbatim, non-empty


def test_vendor_writes_the_template_and_the_manifest_records_it(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    result = vendor(_FRAMEWORK_PKG, tmp_path, framework_version="0.0.0")
    manifest_paths = {rec.path for rec in result.manifest.files}
    for asset in _ASSETS:
        assert (tmp_path / asset).is_file()
        assert asset in manifest_paths
    # the shell still carries the render markers so the vendored renderer can inject into it
    shell = (tmp_path / _ASSETS[0]).read_text(encoding="utf-8")
    assert "<!-- EVALGLASS:STYLE -->" in shell
    assert "<!-- EVALGLASS:DATA -->" in shell
    assert "<!-- EVALGLASS:SCRIPT -->" in shell
