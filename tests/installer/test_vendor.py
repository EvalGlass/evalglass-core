"""S2 (EG-M3-2) — vendoring: namespace rewrite, manifest/lock, host preservation.

Vendoring copies the framework runtime (`core`/`harness`/`adapters` + the package
`__init__`) into ``evals/_evalglass/`` under the ``_evalglass`` namespace (ADR 0011,
option A): every ``import``/``from evalglass…`` statement is rewritten to
``_evalglass`` so the vendored copy is namespace-isolated and importable without an
installed framework. The vendored ``__init__`` carries the pinned version
(version injection). A manifest records a sha256 per managed file; a lock records the
framework identity. Vendoring writes only under the managed root — host-owned truth
is never touched.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import evalglass
from evalglass.installer.contracts import (
    EvalglassLock,
    InstallerError,
    ManagedFileRecord,
    VendorManifest,
)
from evalglass.installer.vendor import MANAGED_ROOT, VendorResult, rewrite_namespace, vendor

_FRAMEWORK_PKG = Path(evalglass.__file__).resolve().parent


# --- namespace rewrite (the riskiest transform) ----------------------------


def test_rewrite_namespace_rewrites_import_statements_only() -> None:
    src = (
        "from evalglass.core import Score\n"
        "import evalglass.harness.cli\n"
        "from evalglass import __version__\n"
        "\n"
        "def f():\n"
        "    from evalglass.harness.runner import run_config  # lazy, indented\n"
        "    return run_config\n"
        "\n"
        '_FRAMEWORK = "evalglass@1.2.3"  # string literal must NOT change\n'
        "# evalglass appears in a comment and must NOT change\n"
        'v = version("evalglass")  # call arg must NOT change\n'
        "evalglassish = 1  # not a word-boundary match\n"
    )
    out = rewrite_namespace(src)
    assert "from _evalglass.core import Score" in out
    assert "import _evalglass.harness.cli" in out
    assert "from _evalglass import __version__" in out
    assert "from _evalglass.harness.runner import run_config" in out
    # Untouched: string literal, comment, call argument, non-word-boundary token.
    assert '"evalglass@1.2.3"' in out
    assert "# evalglass appears in a comment" in out
    assert 'version("evalglass")' in out
    assert "evalglassish = 1" in out
    # No residual top-level evalglass import survived.
    assert "import evalglass" not in out.replace("import evalglass.harness.cli", "")
    for line in out.splitlines():
        stripped = line.strip()
        assert not (stripped.startswith(("from evalglass", "import evalglass")))


def test_rewrite_namespace_leaves_in_string_imports_untouched() -> None:
    """An import-shaped line INSIDE a docstring/string is a literal — never rewritten (ADR 0011)."""
    src = (
        "def f():\n"
        '    """Usage example:\n'
        "    from evalglass.core import Score\n"
        '    """\n'
        "    return 1\n"
        "from evalglass.harness import run\n"  # a real top-level import
    )
    out = rewrite_namespace(src)
    assert "    from evalglass.core import Score" in out, "docstring literal was rewritten"
    assert "from _evalglass.harness import run" in out, "real import was not rewritten"


def test_rewrite_namespace_rewrites_module_path_string_literals() -> None:
    """A runtime import-path string (an ExtensionLane ``module=`` / ``import_module`` arg) is
    rewritten to the vendored namespace — else a vendored host's lane registry imports the absent
    ``evalglass`` package and every opt-in lane breaks. Prose that mentions evalglass stays."""
    src = (
        'LANE = ExtensionLane(module="evalglass.adapters.trace_phoenix")\n'
        "importlib.import_module('evalglass.harness.lanes')\n"
        '"""See evalglass.adapters.trace_phoenix for details."""\n'  # prose, not a bare path
        'framework = "evalglass-teta"\n'  # hyphenated label, not a dotted path
    )
    out = rewrite_namespace(src)
    assert 'module="_evalglass.adapters.trace_phoenix"' in out
    assert "import_module('_evalglass.harness.lanes')" in out
    assert "See evalglass.adapters.trace_phoenix for details" in out  # prose untouched
    assert 'framework = "evalglass-teta"' in out  # label untouched


def test_rewrite_namespace_leaves_filename_literals_untouched() -> None:
    """A quoted ``evalglass.<ext>`` that is a FILENAME (not a managed module path) must NOT be
    rewritten. The rewrite targets only dynamic import paths into managed packages
    (core/harness/adapters); a literal like the ``connect --config`` default ``"evalglass.yaml"``
    is a config filename — rewriting it to ``"_evalglass.yaml"`` silently breaks the vendored CLI
    (regression: the vendored ``connect`` wrote a stray ``_evalglass.yaml`` orphan)."""
    src = (
        '_DEFAULT_CONFIG = "evalglass.yaml"\n'
        '_LOCK = "evalglass.lock"\n'
        '_MINED = "evalglass.discovered.yaml"\n'
        # A real managed import-path string in the same file still IS rewritten:
        'LANE = ExtensionLane(module="evalglass.adapters.trace_langfuse")\n'
    )
    out = rewrite_namespace(src)
    assert '"evalglass.yaml"' in out, "config filename literal was wrongly rewritten"
    assert '"evalglass.lock"' in out, "lock filename literal was wrongly rewritten"
    assert '"evalglass.discovered.yaml"' in out, "mined filename literal was wrongly rewritten"
    assert '"_evalglass.yaml"' not in out
    # The genuine managed module path is still rewritten.
    assert 'module="_evalglass.adapters.trace_langfuse"' in out


def test_vendor_rejects_nonexistent_root(tmp_path: Path) -> None:
    """A misspelled/nonexistent --root must fail closed, never invent an install tree."""
    missing = tmp_path / "nope"
    with pytest.raises(InstallerError):
        vendor(_FRAMEWORK_PKG, missing, framework_version="1.0.0", source_ref="test")
    assert not missing.exists()


# --- vendoring the real framework -------------------------------------------


def _vendor_into(tmp_path: Path, version: str = "1.4.2") -> tuple[Path, VendorResult]:
    host = tmp_path / "host"
    host.mkdir()
    result = vendor(_FRAMEWORK_PKG, host, framework_version=version, source_ref="test")
    return host, result


def test_vendor_writes_managed_runtime_tree(tmp_path: Path) -> None:
    host, _ = _vendor_into(tmp_path)
    managed = host / MANAGED_ROOT
    assert (managed / "__init__.py").is_file()
    for pkg in ("core", "harness", "adapters"):
        assert (managed / pkg / "__init__.py").is_file()
    assert (managed / "core" / "engine.py").is_file()
    assert (managed / "core" / "builtins" / "exact_match.py").is_file()
    assert (managed / "vendor-manifest.json").is_file()
    assert (host / "evals" / "evalglass.lock").is_file()


def test_vendored_tree_has_no_residual_framework_imports(tmp_path: Path) -> None:
    host, _ = _vendor_into(tmp_path)
    managed = host / MANAGED_ROOT
    offenders: list[str] = []
    for py in managed.rglob("*.py"):
        for line in py.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith(("from evalglass", "import evalglass")):
                offenders.append(f"{py.relative_to(managed)}: {s}")
    assert not offenders, f"residual non-rewritten imports: {offenders}"


def test_vendor_injects_pinned_version(tmp_path: Path) -> None:
    host, result = _vendor_into(tmp_path, version="9.9.9")
    init = (host / MANAGED_ROOT / "__init__.py").read_text(encoding="utf-8")
    assert '__version__ = "9.9.9"' in init
    assert result.lock.framework_version == "9.9.9"


def test_vendored_runtime_imports_in_subprocess(tmp_path: Path) -> None:
    """The rewritten tree is a coherent, importable ``_evalglass`` package."""
    host, _ = _vendor_into(tmp_path)
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "import _evalglass.core, _evalglass.harness, _evalglass.adapters; "
        "print(_evalglass.__version__)"
    )
    result = subprocess.run(  # noqa: S603 — fixed interpreter, no shell, test-only
        [sys.executable, "-c", code, str(host / "evals")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1.4.2"


def test_vendor_preserves_host_owned_files(tmp_path: Path) -> None:
    host = tmp_path / "host"
    (host / "evals" / "datasets").mkdir(parents=True)
    gold = host / "evals" / "datasets" / "gold.jsonl"
    gold.write_text('{"input":1}\n', encoding="utf-8")
    before = gold.read_bytes()
    vendor(_FRAMEWORK_PKG, host, framework_version="1.0.0", source_ref="test")
    assert gold.read_bytes() == before, "vendoring touched host-owned truth"
    # And every written managed file is under the managed root (plus the lock).
    manifest_raw = json.loads((host / MANAGED_ROOT / "vendor-manifest.json").read_text())
    for rec in VendorManifest.from_dict(manifest_raw).files:
        assert rec.path.startswith(MANAGED_ROOT + "/")


def test_manifest_checksums_match_disk(tmp_path: Path) -> None:
    host, result = _vendor_into(tmp_path)
    for rec in result.manifest.files:
        on_disk = hashlib.sha256((host / rec.path).read_bytes()).hexdigest()
        assert rec.sha256 == on_disk, f"manifest checksum stale for {rec.path}"


def test_lock_records_installed_features(tmp_path: Path) -> None:
    _, result = _vendor_into(tmp_path)
    assert set(result.lock.installed_features) >= {"core", "harness", "adapters"}
    assert result.lock.optional_extras == []


# --- contract round-trips + fail-closed -------------------------------------


def test_managed_file_record_round_trip() -> None:
    r = ManagedFileRecord(path="evals/_evalglass/core/x.py", sha256="ab", purpose="core")
    assert ManagedFileRecord.from_dict(r.to_dict()) == r


def test_vendor_manifest_round_trip() -> None:
    m = VendorManifest(
        schema_version="1",
        source_version="1.0.0",
        managed_root=MANAGED_ROOT,
        files=[ManagedFileRecord(path="evals/_evalglass/core/x.py", sha256="ab", purpose="core")],
    )
    assert VendorManifest.from_dict(m.to_dict()) == m


def test_lock_round_trip() -> None:
    lock = EvalglassLock(
        schema_version="1",
        framework_version="1.0.0",
        source_ref="evalglass@1.0.0",
        installed_features=["core", "harness", "adapters"],
        optional_extras=[],
    )
    assert EvalglassLock.from_dict(lock.to_dict()) == lock


def test_manifest_rejects_bad_file_record() -> None:
    with pytest.raises(InstallerError):
        VendorManifest.from_dict(
            {
                "schema_version": "1",
                "source_version": "1.0.0",
                "managed_root": MANAGED_ROOT,
                "files": ["not-a-record"],
            }
        )
