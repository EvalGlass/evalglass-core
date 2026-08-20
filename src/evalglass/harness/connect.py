"""``connect`` — bring recorded behavior into a run: local import or live-lane scaffold (Epic B).

Ergonomics + honesty, not new measurement. Two explicit modes share one fail-closed config-editing
core:

* **Local import** (``apply_import``): register an exported trace file as a first-class ``traces:``
  route with no live credentials and no provider SDK. The file is validated with the *same*
  normalizer a ``run`` would use before the config is touched, so a malformed or empty export never
  produces a partial config. The stored path is resolved relative to the config directory (the same
  convention ``run`` uses), so the route works regardless of the working directory.
* **Live scaffold** (``apply_connect``): write/update the correct Langfuse / Phoenix / LangSmith
  connector lane with **env-var-name credentials** (never literal secrets), a **fail-closed**
  ``data_policy`` (defaults to ``unknown`` — a live pull is refused until the host consciously sets
  ``permitted``/``redacted``), and ``enabled: true`` so a following ``run`` executes it through the
  existing seam (ADR 0033-0036, 0046). **No provider SDK / connector *lane* module is imported
  here** — the connector does the transport lazily when a ``run`` resolves the lane.

Both modes **require an existing runnable config** and refuse to invent one silently; passing
``init`` writes a conservative, informational scaffold (never a lanes-only document). Writes are
atomic (temp + replace) and preserve every unknown host key. A trace source — local or live — is
non-reference evidence, so a connected run stays informational and cannot gate.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from evalglass.adapters._connector_boundary import ConnectorConfigError, parse_provider_options
from evalglass.core import ContractError
from evalglass.harness._safe_fs import checked_target
from evalglass.harness.config import LaneConfig, TraceFormat
from evalglass.harness.governance import GovernanceError


class ConnectError(Exception):
    """A fail-closed error building or writing a connect scaffold (a setup error, not a verdict)."""


def _checked_config(path: Path) -> Path:
    """Validate the host-supplied config path before a read/write (resolve + symlink refusal)."""
    try:
        return checked_target(path.resolve().parent, path, what="config")
    except GovernanceError as exc:
        raise ConnectError(str(exc)) from exc


@dataclass(frozen=True)
class _Platform:
    """The static mapping from a user-facing platform to its shipped connector lane."""

    lane: str
    extra: str
    default_endpoint: str
    default_credentials: Mapping[str, str] = field(default_factory=dict)


#: platform -> its connector lane. Credentials default to conventional ENV-VAR **names**
#: (references, never secrets); endpoints default to each provider's public URL (--endpoint wins).
_PLATFORMS: dict[str, _Platform] = {
    "langfuse": _Platform(
        lane="langfuse-trace",
        extra="langfuse-trace",
        default_endpoint="https://cloud.langfuse.com",
        default_credentials={
            "public_key": "LANGFUSE_PUBLIC_KEY",
            "secret_key": "LANGFUSE_SECRET_KEY",
        },
    ),
    "phoenix": _Platform(
        lane="phoenix-trace",
        extra="phoenix-trace",
        default_endpoint="http://localhost:6006",
        default_credentials={},  # keyless-local by default; add an ``api_key`` env-ref for hosted
    ),
    "langsmith": _Platform(
        lane="langsmith-trace",
        extra="langsmith-trace",
        default_endpoint="https://api.smith.langchain.com",
        default_credentials={"api_key": "LANGSMITH_API_KEY"},
    ),
}


def platforms() -> list[str]:
    """The live platforms ``connect --live`` understands."""
    return sorted(_PLATFORMS)


def connector_lane_config(
    platform: str,
    *,
    endpoint: str | None = None,
    project: str | None = None,
    credentials: Mapping[str, str] | None = None,
    data_policy: str = "unknown",
    limit: int | None = None,
) -> dict[str, Any]:
    """Turn ``(platform, options)`` into a validated, enabled ``LaneConfig`` mapping (EG-P2-1).

    Credentials are environment-variable **names** (references), never literal secrets — a literal
    is rejected by :func:`parse_provider_options`, whose error never echoes the value.
    ``data_policy`` defaults to ``unknown`` (fail-closed egress). ``enabled`` is ``True`` so a
    following ``run`` executes the lane. Raises :class:`ConnectError` on any malformed input.
    """
    spec = _PLATFORMS.get(platform)
    if spec is None:
        raise ConnectError(
            f"unknown live platform {platform!r}; choose one of: {', '.join(platforms())}"
        )
    creds = dict(spec.default_credentials if credentials is None else credentials)
    options: dict[str, Any] = {"endpoint": endpoint or spec.default_endpoint}
    if creds:
        options["credentials"] = creds
    if project is not None:
        options["project"] = project
    if limit is not None:
        options["limit"] = limit
    # Fail closed on a literal secret / malformed option BEFORE writing anything — the same
    # boundary the connector applies at run time, so the scaffold can never emit an invalid lane.
    try:
        parse_provider_options(options)
    except ConnectorConfigError as exc:
        raise ConnectError(str(exc)) from exc
    lane = {"name": spec.lane, "enabled": True, "data_policy": data_policy, "options": options}
    # Guarantee the scaffold is a runnable lane (known name, valid data_policy) via a round-trip.
    try:
        LaneConfig.from_mapping(lane, 0)
    except ContractError as exc:
        raise ConnectError(str(exc)) from exc
    return lane


def _scaffold_config_doc() -> dict[str, Any]:
    """A minimal, conservative, **informational** config (never a lanes-only document).

    Used only by ``--init``. It carries the deterministic structural floor — a well-formed run that
    loads through :class:`RuntimeConfig` and cannot gate (no ``gating`` metric, no approved
    threshold), so an initialized config is honest evidence, never a silent pass.
    """
    return {
        "run": {"id": "eval"},
        "metrics": [
            {
                "name": "structural_shape",
                "evaluator_ref": "structural_shape@1",
                "lens": "non_reference",
                "score_type": "binary",
            },
            {
                "name": "field_presence",
                "evaluator_ref": "field_presence@1",
                "lens": "non_reference",
                "score_type": "continuous",
                "score_range": [0, 1],
                "params": {"required_fields": ["output"]},
            },
        ],
        "output": {"dir": "reports"},
    }


def _load_config_doc(path: Path, *, init: bool) -> dict[str, Any]:
    """Load the editable config mapping, or fail closed unless ``init`` is asked for.

    A present, non-empty mapping is edited in place. A missing or empty config is refused by
    default (the connect footgun: a silently-bootstrapped lanes-only file); ``init`` instead writes
    the conservative informational scaffold. A present-but-non-mapping config always fails closed.
    """
    if path.exists():
        loaded = yaml.safe_load(_checked_config(path).read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
        if loaded is not None:
            raise ConnectError(f"{path}: evalglass.yaml must be a mapping to edit it")
        # An existing but empty file is not a runnable config.
    if init:
        return _scaffold_config_doc()
    raise ConnectError(
        f"{path}: no runnable evalglass.yaml here — pass init to create a conservative "
        "informational config, or point --config at an existing one"
    )


def _write_config_doc(path: Path, doc: Mapping[str, Any]) -> None:
    """Write ``doc`` back as YAML atomically (temp + os.replace), preserving every host key.

    (YAML comments are not preserved: PyYAML has no comment-round-trip API, so the verb rewrites
    the data. The atomic replace means a crashed write never leaves a truncated config.)
    """
    safe = _checked_config(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp = safe.parent / f"{safe.name}.tmp"
    tmp.write_text(yaml.safe_dump(dict(doc), sort_keys=False), encoding="utf-8")
    os.replace(tmp, safe)


def _collection_list(doc: Mapping[str, Any], collection: str) -> list[Any]:
    """A mutable copy of ``doc[collection]`` as a list; absent is empty, non-list fails closed."""
    raw = doc.get(collection)
    if raw is None:
        return []
    if isinstance(raw, list):
        return list(raw)
    raise ConnectError(f"'{collection}' must be a list to add an entry")


def _upsert(doc: dict[str, Any], collection: str, entry: dict[str, Any], *, key: str) -> bool:
    """Replace the first ``collection`` entry whose ``key`` matches ``entry``, else append it.

    Returns ``True`` when an existing entry was replaced (idempotent re-run), ``False`` on append.
    A present-but-non-list collection fails closed.
    """
    items = _collection_list(doc, collection)
    for i, existing in enumerate(items):
        if isinstance(existing, Mapping) and existing.get(key) == entry[key]:
            items[i] = entry
            doc[collection] = items
            return True
    items.append(entry)
    doc[collection] = items
    return False


def apply_connect(
    config_path: str | Path, platform: str, *, init: bool = False, **options: Any
) -> dict[str, Any]:
    """Upsert the connector lane into ``evalglass.yaml`` idempotently, preserving host keys.

    Requires an existing runnable config (or ``init`` to scaffold a conservative informational one).
    **Replaces** any lane entry with the same name (so re-running updates in place, never
    duplicating) and appends otherwise, then writes it back atomically. Every other config key —
    datasets, metrics, traces, other lanes — is preserved. Returns the lane mapping written. Raises
    :class:`ConnectError` on a malformed platform/options or a config that cannot hold a lane.
    """
    path = Path(config_path)
    lane = connector_lane_config(platform, **options)
    doc = _load_config_doc(path, init=init)
    _upsert(doc, "lanes", lane, key="name")
    _write_config_doc(path, doc)
    return lane


def apply_import(
    config_path: str | Path,
    from_path: str | Path,
    *,
    fmt: str = "local",
    init: bool = False,
) -> dict[str, Any]:
    """Register a local exported trace file as a first-class ``traces:`` route (Epic B, B1).

    Validates the export with the same normalizer a ``run`` uses **before** touching the config, so
    a missing / empty / unparseable / zero-unit export raises :class:`ConnectError` and writes
    nothing. The stored path is config-directory-relative (matching how ``run`` resolves it), so the
    route is independent of the working directory. Idempotent by resolved path — re-importing the
    same file updates its entry rather than duplicating it. Returns a summary of what changed
    (``path`` written, ``format``, unit ``records`` counted, and ``created``/``updated``).
    """
    path = Path(config_path)
    try:
        trace_format = TraceFormat(fmt)
    except ValueError as exc:
        allowed = ", ".join(f.value for f in TraceFormat)
        raise ConnectError(f"unknown import format {fmt!r}; choose one of: {allowed}") from exc

    config_dir = path.resolve().parent
    source = Path(from_path)
    if not source.is_file():
        raise ConnectError(f"import file not found: {from_path}")
    source_abs = source.resolve()
    # Validate on the absolute path so validation never depends on the config dir existing yet
    # (it may be created by --init only after this check). The stored path is config-relative so a
    # `run` from any working directory resolves the same file.
    records = _validate_local_import(source_abs, trace_format)
    stored = os.path.relpath(source_abs, config_dir)

    doc = _load_config_doc(path, init=init)
    entry = {"path": stored, "format": trace_format.value}
    replaced = _upsert_trace(doc, entry, config_dir)
    _write_config_doc(path, doc)
    return {
        "path": stored,
        "format": trace_format.value,
        "records": records,
        "created": not replaced,
        "updated": replaced,
    }


def _upsert_trace(doc: dict[str, Any], entry: dict[str, Any], config_dir: Path) -> bool:
    """Upsert a ``traces:`` entry, matching an existing one by its *resolved* path (idempotent)."""
    items = _collection_list(doc, "traces")
    target = (config_dir / entry["path"]).resolve()
    for i, existing in enumerate(items):
        if (
            isinstance(existing, Mapping)
            and "path" in existing
            and (config_dir / str(existing["path"])).resolve() == target
        ):
            items[i] = entry
            doc["traces"] = items
            return True
    items.append(entry)
    doc["traces"] = items
    return False


def _validate_local_import(source_abs: Path, fmt: TraceFormat) -> int:
    """Read the export with the production trace adapter; return the unit count (fail-closed).

    Reusing the real normalizer means the validation is honest — the config is only written if the
    file yields at least one normalized unit through the exact route a ``run`` will use. Zero units
    (empty or wholly malformed) or an adapter setup error raises :class:`ConnectError`. The adapter
    is given the export's own directory as its root and the bare filename, so validation never
    depends on the config directory (which ``--init`` may not have created yet). Imported lazily so
    the module stays import-light and the connect verb keeps its no-lane-module boundary (these
    local adapters are SDK-free and are not connector lanes).
    """
    from evalglass.harness.config import TraceConfig
    from evalglass.harness.errors import SetupError

    cfg = TraceConfig(path=source_abs.name, name=source_abs.name, fmt=fmt)
    root = source_abs.parent
    try:
        if fmt is TraceFormat.LOCAL:
            from evalglass.adapters.trace_jsonl import LocalJsonlTraceSource

            read = LocalJsonlTraceSource(cfg, root).read()
        else:
            from evalglass.adapters.trace_open_convention import OpenConventionTraceSource

            read = OpenConventionTraceSource(cfg, root).read()
    except SetupError as exc:
        raise ConnectError(f"cannot import {source_abs.name} as {fmt.value}: {exc}") from exc
    if not read.units:
        detail = f" ({len(read.diagnostics)} record(s) rejected)" if read.diagnostics else ""
        raise ConnectError(
            f"import produced no usable units from {source_abs.name} as {fmt.value}{detail}; "
            "nothing was written"
        )
    return len(read.units)
