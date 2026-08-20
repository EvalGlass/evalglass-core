"""Vendoring the managed runtime into a host repo (EG-M3-2; ADR 0011, option A).

``vendor`` copies the framework's ``core``/``harness``/``adapters`` packages (and the
top-level package ``__init__``) into ``<host>/evals/_evalglass/``, rewriting every
``import``/``from evalglass…`` statement to ``_evalglass`` so the vendored copy is
**namespace-isolated** (it can never bind an installed ``evalglass``) and importable
without the framework on ``sys.path``. The vendored ``__init__`` gets the pinned
version baked in (version injection), so host provenance reports the real version
rather than ``evalglass@0.0.0``. A ``vendor-manifest.json`` records a sha256 per
managed file; an ``evalglass.lock`` records the framework identity. Vendoring writes
**only** under the managed root (plus the lock) — host-owned truth is never touched.

This is integration-time code: effectful by design, and never imported by the runtime
(`core`/`harness`/`adapters`) — enforced by ``tests/core_isolation/test_installer_boundary``.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from evalglass.installer.contracts import (
    EvalglassLock,
    InstallerError,
    ManagedFileRecord,
    VendorManifest,
)

MANAGED_ROOT = "evals/_evalglass"
MANAGED_PACKAGES = ("core", "harness", "adapters")
_MANIFEST_SCHEMA = "1"
_LOCK_SCHEMA = "1"

# Applied only to physical lines that ``ast`` identifies as real ``evalglass`` import
# statements (see ``rewrite_namespace``); within such a line it rewrites the package root
# token ``evalglass`` to ``_evalglass``.
_IMPORT_RE = re.compile(r"^(\s*)(from|import)\s+evalglass\b")
# A pure quoted dotted module-path literal INTO a managed package, e.g.
# ``"evalglass.adapters.trace_phoenix"`` — the runtime import path an ExtensionLane / dynamic
# ``import_module`` uses (ADR 0011). Restricted to the managed packages (core/harness/adapters) so a
# quoted *filename* like ``"evalglass.yaml"`` / ``"evalglass.lock"`` — not an importable module — is
# left untouched; rewriting those to ``"_evalglass.yaml"`` silently broke the vendored ``connect``
# CLI default. Prose and docstrings never match: the quote must sit immediately before ``evalglass``
# and immediately after the dotted path, so an example ``from evalglass.core import X`` inside a
# docstring is untouched.
_MANAGED_MODULE_ALT = "|".join(re.escape(pkg) for pkg in MANAGED_PACKAGES)
_MODULE_STR_RE = re.compile(
    rf"""(["'])evalglass(\.(?:{_MANAGED_MODULE_ALT})(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\1"""
)
_VERSION_RE = re.compile(r"""__version__\s*=\s*["'][^"']*["']""")


@dataclass(frozen=True)
class VendorResult:
    """The outcome of a vendor run: the manifest, the lock, and the files written."""

    manifest: VendorManifest
    lock: EvalglassLock
    written: list[str]


def rewrite_namespace(source: str) -> str:
    """Rewrite ``import``/``from evalglass…`` statements to the ``_evalglass`` namespace.

    Import-scoped via ``ast``: only physical lines that are real absolute ``evalglass``
    import statements are touched, so string literals, docstrings, comments, and call
    arguments (e.g. an example ``from evalglass…`` line inside a docstring) are left
    exactly as-is (ADR 0011).
    """
    tree = ast.parse(source)
    import_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name == "evalglass" or a.name.startswith("evalglass.") for a in node.names):
                import_lines.add(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level == 0 and (mod == "evalglass" or mod.startswith("evalglass.")):
                import_lines.add(node.lineno)
    lines = source.splitlines(keepends=True)
    for lineno in import_lines:
        lines[lineno - 1] = _IMPORT_RE.sub(r"\1\2 _evalglass", lines[lineno - 1])
    result = "".join(lines)
    # Also rewrite runtime import-path STRING literals (e.g. an ExtensionLane ``module=`` or a
    # dynamic ``import_module("evalglass.…")``) — without this a vendored host's lane registry
    # imports the un-vendored ``evalglass`` namespace, which does not exist in the host (every
    # opt-in lane breaks). Only pure quoted dotted paths match, so prose stays untouched.
    return _MODULE_STR_RE.sub(r"\1_evalglass\2\1", result)


def _inject_version(init_source: str, version: str) -> str:
    rewritten, n = _VERSION_RE.subn(f'__version__ = "{version}"', init_source)
    if n == 0:
        # The package __init__ must declare __version__ so vendoring can pin it; fail closed.
        raise InstallerError("vendor: framework __init__ has no __version__ to pin")
    return rewritten


def _iter_package_files(pkg_dir: Path) -> list[Path]:
    return sorted(p for p in pkg_dir.rglob("*.py") if "__pycache__" not in p.parts)


#: Non-Python packaged assets the runtime loads at render time (the dashboard template). Vendored
#: verbatim (no namespace rewrite — they carry no Python import path), so a host's vendored renderer
#: has its template on disk and ``report.html`` renders after the plugin is removed (EG-DX-E2).
_ASSET_SUFFIXES = (".html", ".css", ".js")


def _iter_asset_files(framework_pkg: Path) -> list[Path]:
    reporting = framework_pkg / "harness" / "reporting"
    if not reporting.is_dir():
        return []
    return sorted(
        p
        for p in reporting.rglob("*")
        if p.is_file() and p.suffix in _ASSET_SUFFIXES and "__pycache__" not in p.parts
    )


@dataclass(frozen=True)
class ManagedContent:
    """One managed file's host-relative path, vendored content, and purpose (no I/O)."""

    path: str
    content: str
    purpose: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


def managed_files(framework_pkg: Path, framework_version: str) -> list[ManagedContent]:
    """Compute the managed files (rewritten + version-injected) **without writing** them.

    Shared by :func:`vendor` (which writes them) and the re-vendor planner (which diffs
    them against what is on disk), so the two can never disagree about what is managed.
    """
    framework_pkg = Path(framework_pkg)
    out: list[ManagedContent] = []
    init_src = (framework_pkg / "__init__.py").read_text(encoding="utf-8")
    out.append(
        ManagedContent(
            f"{MANAGED_ROOT}/__init__.py",
            _inject_version(rewrite_namespace(init_src), framework_version),
            "package",
        )
    )
    for pkg in MANAGED_PACKAGES:
        pkg_dir = framework_pkg / pkg
        if not pkg_dir.is_dir():
            raise InstallerError(f"vendor: framework package {pkg!r} not found at {pkg_dir}")
        for path in _iter_package_files(pkg_dir):
            rel = path.relative_to(framework_pkg).as_posix()
            out.append(
                ManagedContent(
                    f"{MANAGED_ROOT}/{rel}",
                    rewrite_namespace(path.read_text(encoding="utf-8")),
                    pkg,
                )
            )
    # Packaged non-Python assets (the dashboard template) — copied verbatim under the harness tree.
    for path in _iter_asset_files(framework_pkg):
        rel = path.relative_to(framework_pkg).as_posix()
        out.append(
            ManagedContent(f"{MANAGED_ROOT}/{rel}", path.read_text(encoding="utf-8"), "harness")
        )
    return out


def write_manifest_and_lock(
    host_root: Path,
    records: list[ManagedFileRecord],
    *,
    framework_version: str,
    source_ref: str | None,
) -> tuple[VendorManifest, EvalglassLock]:
    """Write ``vendor-manifest.json`` + ``evalglass.lock`` for the given managed records."""
    manifest = VendorManifest(
        schema_version=_MANIFEST_SCHEMA,
        source_version=framework_version,
        managed_root=MANAGED_ROOT,
        files=records,
    )
    features = sorted({r.purpose for r in records} & set(MANAGED_PACKAGES))
    lock = EvalglassLock(
        schema_version=_LOCK_SCHEMA,
        framework_version=framework_version,
        source_ref=source_ref or f"evalglass@{framework_version}",
        installed_features=features,
        optional_extras=[],
    )
    (host_root / MANAGED_ROOT / "vendor-manifest.json").write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (host_root / "evals" / "evalglass.lock").write_text(
        json.dumps(lock.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest, lock


def vendor(
    framework_pkg: Path,
    host_root: Path,
    *,
    framework_version: str,
    source_ref: str | None = None,
) -> VendorResult:
    """Vendor the managed runtime into ``host_root/evals/_evalglass`` and write manifest + lock."""
    host_root = Path(host_root)
    # The host repo must already exist — never invent an install tree for a mistyped root.
    if not host_root.is_dir():
        raise InstallerError(f"vendor: host root {host_root} does not exist or is not a directory")

    records: list[ManagedFileRecord] = []
    written: list[str] = []
    for mc in managed_files(framework_pkg, framework_version):
        dest = host_root / mc.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        # write_bytes (not write_text) so LF is preserved on every platform — the manifest
        # sha256 is computed over the LF-encoded content, so a CRLF translation would make a
        # fresh install's bytes disagree with its own manifest (false host-patch on re-vendor).
        dest.write_bytes(mc.content.encode("utf-8"))
        records.append(ManagedFileRecord(path=mc.path, sha256=mc.sha256, purpose=mc.purpose))
        written.append(mc.path)

    manifest, lock = write_manifest_and_lock(
        host_root, records, framework_version=framework_version, source_ref=source_ref
    )
    return VendorResult(manifest=manifest, lock=lock, written=written)
