"""Shared provider-connector boundary helpers (EG-R0-3; ADR 0033).

The live trace connectors (Langfuse / Phoenix / LangSmith, EG-R1…R3) attach through one shared
boundary so they stay consistent without a second trace runtime. This module holds the connector
plumbing that is *not* already in :mod:`evalglass.adapters._span_mapping` (which owns the
open-convention span → :class:`~evalglass.core.TraceEnvelope` mapping reused here): lazy SDK import,
endpoint/credential prerequisites, in-memory span normalization, and cursor pagination.

Boundary rules (ADR 0033):

- **A connector imports evidence, never authority.** Every helper returns ``TraceEnvelope``/
  ``EvalUnit``-ready data (a :class:`~evalglass.harness.ports.TraceRead`) or a typed
  :class:`~evalglass.core.Diagnostic` — never a ``Score``, verdict, or authority.
- **The SDK is imported lazily, by name, inside the lane call path.** This module imports only the
  standard library and the effect-free core/ports; it never statically imports a provider SDK, so
  ``check_no_provider_sdk`` sees it as hermetic and importing it never requires an extra.
- **A missing extra / endpoint / credential is a clean** :class:`MissingPrerequisite` **skip**,
  never an ``ImportError`` crash.
- **Only normalized records cross the boundary.** Vendor wrapper objects, cursors, and
  client/project objects are dropped — only a span's known fields are mapped.
"""

from __future__ import annotations

import importlib
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from evalglass.adapters._span_mapping import map_span, policy_or_unknown
from evalglass.core import DataPolicy, Diagnostic, Severity
from evalglass.harness.coverage import (
    TRACE_LEVEL_FALLBACK_SPAN_KEY,
    SourceImportManifest,
    availability_from_behaviors,
    derive_completeness,
)
from evalglass.harness.lanes import LaneError, LaneResult, LaneStatus, MissingPrerequisite
from evalglass.harness.ports import TraceRead, TraceUnit

#: The data policies that permit egress (mirrors ``authority._POLICY_OK`` / the dashboard sink).
#: A connector makes a live call only on a genuine ``permitted``/``redacted`` — never on
#: ``forbidden``/``missing``/``unknown`` (which fail closed).
_EGRESS_OK = frozenset({DataPolicy.PERMITTED, DataPolicy.REDACTED})


class ConnectorConfigError(LaneError):
    """A provider lane's options are structurally invalid (fail-closed).

    A subclass of :class:`LaneError` so the runner seam turns it into a ``BLOCKED`` lane result —
    a bad option is a visible setup error, never an unhandled crash or a fabricated score.
    """


def lazy_import(module_name: str, *, extra: str) -> Any:
    """Import a provider SDK lazily, by name; a missing optional extra is a clean skip.

    The connector calls this **inside** its lane path, so importing the connector module (for
    metadata / deletion / mapping tests) never requires the SDK. An absent module means the opt-in
    ``extra`` is not installed — a :class:`MissingPrerequisite` with a pip-install hint, never an
    uncaught ``ImportError``.
    """
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise MissingPrerequisite(
            f"the {extra!r} optional extra is not installed (no module {module_name!r}); "
            f"install it with: pip install 'evalglass[{extra}]'"
        ) from exc


def require_prerequisite(value: str | None, *, what: str) -> str:
    """Return a non-blank prerequisite (endpoint, project, …) or raise a clean skip.

    An absent/blank endpoint or credential is an *expected* opt-in state, not a defect: the lane is
    unavailable and skips with a :class:`MissingPrerequisite`, never fabricating a score.
    """
    if value is None or not value.strip():
        raise MissingPrerequisite(f"the connector lane is unavailable: no {what} configured")
    return value.strip()


def read_env_credential(env_var: str) -> str | None:
    """Read a credential from the environment by variable name; blank/unset reads as ``None``.

    Credentials are host-owned environment-variable *references* (ADR 0033): the connector reads the
    secret only when the lane is enabled, and never writes it to any artifact. This helper only
    reads — it never logs, returns, or persists the value beyond the caller.
    """
    raw = os.environ.get(env_var)
    return raw.strip() if raw and raw.strip() else None


def _no_metadata(span: Mapping[str, Any]) -> dict[str, Any]:
    del span
    return {}


def normalize_spans(
    spans: object,
    *,
    name: str,
    source: str,
    data_policy: str,
    provenance: dict[str, Any],
    malformed_code: str,
    location: str,
    build_metadata: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
    include_timing: bool = True,
) -> TraceRead:
    """Normalize an **already-fetched** provider span list to a :class:`TraceRead` (fail-closed).

    The connector fetches spans via its SDK, then hands the *list* here; only each span's known
    open-convention fields are mapped (via the shared :func:`map_span`), so any vendor wrapper
    handed alongside the list — or vendor keys outside a span's ``attributes`` — never reach the
    core-visible path. A non-list ``spans`` is a single ``malformed_code`` diagnostic with no units;
    a per-span failure is a diagnostic while the remaining good spans still map.
    """
    metadata = build_metadata if build_metadata is not None else _no_metadata
    policy = policy_or_unknown(data_policy)
    if not isinstance(spans, list):
        diag = Diagnostic(
            code=malformed_code,
            severity=Severity.ERROR,
            message="provider response has no spans list",
            location=location,
        )
        return TraceRead(name=name, data_policy=policy, units=[], diagnostics=[diag])

    units: list[TraceUnit] = []
    diagnostics: list[Diagnostic] = []
    for index, span in enumerate(spans):
        # The provider-supplied ``build_metadata`` runs inside ``map_span``; a single span that
        # makes it raise must become a diagnostic, not abort the whole read and discard
        # already-mapped good units (the partial-failure contract).
        try:
            mapped: TraceUnit | Diagnostic = map_span(
                span,
                index,
                source=source,
                name=name,
                location_prefix=location,
                data_policy=data_policy,
                build_metadata=metadata,
                provenance=provenance,
                include_timing=include_timing,
            )
        except Exception as exc:  # a provider mapping/metadata fault → a diagnostic, never a crash
            mapped = Diagnostic(
                code=malformed_code,
                severity=Severity.ERROR,
                message=f"span mapping failed: {exc}",
                location=f"{location}#span{index}",
            )
        if isinstance(mapped, TraceUnit):
            units.append(mapped)
        else:
            diagnostics.append(mapped)
    return TraceRead(name=name, data_policy=policy, units=units, diagnostics=diagnostics)


def collect_pages(
    fetch_page: Callable[[str | None], Mapping[str, Any]],
    *,
    items_key: str,
    cursor_key: str,
    malformed_code: str,
    location: str,
    max_pages: int = 100,
) -> tuple[list[Any], list[Diagnostic]]:
    """Walk a provider's cursor-paginated response, fail-closed.

    Calls ``fetch_page(cursor)`` until the response carries no next cursor. A fetch error, a
    malformed page (no ``items_key`` list), a repeated cursor (a provider loop), or exceeding
    ``max_pages`` each surface a typed ``malformed_code`` diagnostic and stop — never an infinite
    loop, a duplicated page, or a silently dropped error page. Items collected before the fault are
    preserved (a partial read is visible, not discarded).
    """
    items: list[Any] = []
    diagnostics: list[Diagnostic] = []
    seen_cursors: set[str] = set()
    cursor: str | None = None

    def diag(message: str) -> Diagnostic:
        return Diagnostic(
            code=malformed_code, severity=Severity.ERROR, message=message, location=location
        )

    for _ in range(max_pages):
        try:
            page = fetch_page(cursor)
        except Exception as exc:  # provider/transport error → a visible diagnostic, never a crash
            diagnostics.append(diag(f"provider page fetch failed: {exc}"))
            return items, diagnostics
        if not isinstance(page, Mapping) or not isinstance(page.get(items_key), list):
            diagnostics.append(diag(f"provider page has no {items_key!r} list"))
            return items, diagnostics
        items.extend(page[items_key])
        next_cursor = page.get(cursor_key)
        if not next_cursor or not isinstance(next_cursor, str):
            return items, diagnostics
        if next_cursor in seen_cursors:
            diagnostics.append(diag(f"pagination cursor {next_cursor!r} repeated; stopping"))
            return items, diagnostics
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    diagnostics.append(diag(f"pagination exceeded {max_pages} pages; stopping"))
    return items, diagnostics


# --- provider lane config + credential conventions (EG-R0-4) -----------------

#: The option keys every provider connector lane accepts. Credentials are env-var *references*
#: (names), never inline secrets; the time window and limit bound a single read.
_COMMON_OPTION_KEYS = frozenset(
    {"endpoint", "project", "query", "limit", "start_time", "end_time", "credentials"}
)

#: A POSIX environment-variable *name* (what a credential value must be — a reference, not a
#: secret). A literal token (``sk-live-…``) contains characters outside this set and is rejected.
_ENV_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ProviderLaneOptions:
    """Parsed, validated options common to every provider connector lane (ADR 0033).

    ``credentials`` maps a logical name to an **environment-variable name** — a *reference*, never
    a secret value. The secret materializes only when :func:`resolve_credentials` reads it for a
    live call; the options themselves are safe to record in provenance.
    """

    endpoint: str | None = None
    project: str | None = None
    query: str | None = None
    limit: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    credentials: Mapping[str, str] = field(default_factory=dict)


def parse_provider_options(options: Any, *, extra_keys: Sequence[str] = ()) -> ProviderLaneOptions:
    """Validate a provider lane's ``options`` mapping, failing closed on anything malformed.

    Unknown keys, wrongly-typed values, a non-positive ``limit``, or credentials that are not a
    ``{name: ENV_VAR}`` mapping each raise :class:`ConnectorConfigError` (a ``LaneError`` the seam
    blocks). ``extra_keys`` lets a provider declare provider-specific options without reopening the
    fail-closed default.
    """
    if not isinstance(options, Mapping):
        raise ConnectorConfigError(
            f"connector options must be a mapping, got {type(options).__name__}"
        )
    allowed = _COMMON_OPTION_KEYS | set(extra_keys)
    unknown = sorted(k for k in options if k not in allowed)
    if unknown:
        raise ConnectorConfigError(
            f"unknown connector option(s): {unknown}; allowed: {sorted(allowed)}"
        )

    def opt_str(key: str) -> str | None:
        value = options.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ConnectorConfigError(f"option {key!r} must be a non-empty string, got {value!r}")
        return value.strip()

    limit = options.get("limit")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0):
        raise ConnectorConfigError(f"option 'limit' must be a positive integer, got {limit!r}")

    raw_creds = options.get("credentials", {})
    if not isinstance(raw_creds, Mapping):
        raise ConnectorConfigError("option 'credentials' must be a mapping of name -> ENV_VAR ref")
    for logical, ref in raw_creds.items():
        if not isinstance(logical, str) or not logical.strip():
            raise ConnectorConfigError("a credential key must be a non-blank string")
        # The value must be an env-var NAME (a reference), never a literal secret. The error never
        # echoes the value — a rejected literal secret must not leak into the blocked diagnostic.
        if not isinstance(ref, str) or not _ENV_VAR_NAME_RE.match(ref):
            raise ConnectorConfigError(
                f"credential {logical!r} must reference an environment-variable NAME "
                f"(e.g. MY_API_KEY), not a literal secret value"
            )

    return ProviderLaneOptions(
        endpoint=opt_str("endpoint"),
        project=opt_str("project"),
        query=opt_str("query"),
        limit=limit,
        start_time=opt_str("start_time"),
        end_time=opt_str("end_time"),
        credentials={k: v.strip() for k, v in raw_creds.items()},
    )


def egress_permitted(policy: DataPolicy) -> bool:
    """True only for ``permitted``/``redacted`` — the policies that allow a live provider call."""
    return policy in _EGRESS_OK


def egress_gate(policy: DataPolicy, *, lane: str, code: str) -> LaneResult | None:
    """Egress-before-effects: return a ``BLOCKED`` lane result if the policy forbids egress.

    Called by a connector **before** any live SDK call, so ``forbidden``/``missing``/``unknown``
    never reach the network. Returns ``None`` when egress is permitted (the connector proceeds).
    """
    if egress_permitted(policy):
        return None
    return LaneResult(
        lane=lane,
        status=LaneStatus.BLOCKED,
        report=f"egress refused before request: data_policy={policy.value}",
        diagnostics=[
            Diagnostic(
                code=code,
                severity=Severity.ERROR,
                message=f"data policy {policy.value} forbids egress; no provider call made",
                location=lane,
            )
        ],
    )


def resolve_credentials(refs: Mapping[str, str]) -> dict[str, str]:
    """Resolve ``{logical: ENV_VAR}`` references to ``{logical: secret}`` from the environment.

    Only env-var *names* live in config; the resolved secret stays in memory for the client call
    and is never returned to any persisted structure by the boundary. An absent reference is omitted
    (the connector decides which credentials are required via :func:`require_prerequisite`), never a
    crash.
    """
    resolved: dict[str, str] = {}
    for logical, env_var in refs.items():
        secret = read_env_credential(env_var)
        if secret is not None:
            resolved[logical] = secret
    return resolved


# --- shared TraceSource connector skeleton (EG-R2; ADR 0033) -----------------


class BaseTraceConnector:
    """Shared :class:`~evalglass.harness.ports.TraceSource` skeleton for SDK connectors.

    Factors the whole flow common to every provider connector — the runner-compatible constructor,
    the egress-before-effects gate, the fetch dispatch (injected ``fetch`` vs the lazy default), the
    malformed/skip fail-closed paths, and folding per-entry diagnostics into the ``TraceRead`` — so
    each provider adapter supplies only what differs: the class-vars below, the native →
    open-convention mapping (:meth:`_to_open_convention`), and the live fetch
    (:meth:`_default_fetch`).

    A connector imports **evidence, never authority**: ``read()`` returns a ``TraceRead`` only. The
    diagnostic codes are derived from :attr:`provider` (``<provider>_malformed_response`` /
    ``<provider>_egress_forbidden``).
    """

    #: Provider-specific class-vars (set by each subclass).
    extra: ClassVar[str]  # the optional extra key (e.g. "langfuse-trace")
    lane: ClassVar[str]  # the lane name / TraceEnvelope source
    provider: ClassVar[str]  # the vendor-neutral provider tag (e.g. "langfuse")
    import_name: ClassVar[str]  # the SDK module to lazy-import (e.g. "phoenix.client")
    endpoint_label: ClassVar[str] = "provider endpoint"  # what a missing endpoint is called
    option_extra_keys: ClassVar[tuple[str, ...]] = ()  # provider-specific option keys

    def __init__(
        self,
        *,
        root: Path | None = None,
        data_policy: str = "unknown",
        fetch: Callable[[], Mapping[str, Any]] | None = None,
        **options: Any,
    ) -> None:
        # The runner seam calls factory(root=root, data_policy=..., **lane_options) (flattened); a
        # connector reads from the provider, not the local repo, so ``root`` is accepted + ignored.
        del root
        self._opts = parse_provider_options(options, extra_keys=self.option_extra_keys)
        self._endpoint = require_prerequisite(self._opts.endpoint, what=self.endpoint_label)
        self._data_policy = policy_or_unknown(data_policy)
        self._fetch = fetch

    def read(self) -> TraceRead:
        malformed = f"{self.provider}_malformed_response"
        # EGRESS-BEFORE-EFFECTS: a non-egress policy refuses the pull before any client call.
        if not egress_permitted(self._data_policy):
            return self._diag_read(
                f"{self.provider}_egress_forbidden",
                f"data policy {self._data_policy.value} forbids egress; no {self.provider} call",
            )
        try:
            payload = self._fetch_payload()
            # Optional provider hydration (B3): a provider may fetch bounded child observations to
            # deepen the payload before pure mapping. It runs AFTER the single egress gate above, so
            # every hydration effect is already policy-checked; a shortfall stays partial, not a
            # crash. Default is identity (no hydration).
            payload = self._enrich_payload(payload)
        except MissingPrerequisite:
            # Absent extra/endpoint → a clean skip at the seam, not a malformed block.
            raise
        except Exception as exc:  # provider/transport fault → a diagnostic, never a crash
            return self._diag_read(malformed, f"{self.provider} fetch failed: {exc}")
        spans, pre_diagnostics = self._to_open_convention(payload)
        read = normalize_spans(
            spans,
            name=self.lane,
            source=self.lane,
            data_policy=self._data_policy.value,
            provenance={"trace": self.lane, "provider": self.provider},
            build_metadata=self._build_metadata,
            malformed_code=malformed,
            location=f"{self.provider}://{self._endpoint}",
        )
        diagnostics = [*pre_diagnostics, *read.diagnostics]
        span_list = spans if isinstance(spans, list) else []
        # A record is one provider span plus any entry that failed before it could become a span.
        records_seen = len(span_list) + len(pre_diagnostics)
        # Fallback spans are marked with a top-level key map_span ignores; a fallback that mapped is
        # coarser than hydrated evidence, so any fallback forces the source to read as partial.
        fallback = sum(
            1 for s in span_list if isinstance(s, Mapping) and s.get(TRACE_LEVEL_FALLBACK_SPAN_KEY)
        )
        manifest = self._manifest(
            records_seen=records_seen,
            units_emitted=len(read.units),
            rejected=len(diagnostics),
            trace_level_fallback=fallback,
            diagnostics=diagnostics,
            availability=availability_from_behaviors([u.envelope.behavior for u in read.units]),
        )
        # A malformed entry surfaces a diagnostic, never a silent drop into an empty, clean read.
        return TraceRead(
            name=read.name,
            data_policy=read.data_policy,
            units=read.units,
            diagnostics=diagnostics,
            manifest=manifest,
        )

    def _fetch_payload(self) -> Mapping[str, Any]:
        return self._fetch() if self._fetch is not None else self._default_fetch()

    def _enrich_payload(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Provider hook to deepen a fetched payload (bounded child hydration); default identity."""
        return payload

    def _build_metadata(self, span: Mapping[str, Any]) -> dict[str, Any]:
        # A connector stashes vendor-neutral metadata under ``_eg_metadata`` while mapping; absent
        # for providers (like Phoenix) that carry none.
        stashed = span.get("_eg_metadata")
        return dict(stashed) if isinstance(stashed, Mapping) else {}

    def _malformed(self, message: str) -> Diagnostic:
        return Diagnostic(
            code=f"{self.provider}_malformed_response",
            severity=Severity.ERROR,
            message=message,
            location=self.lane,
        )

    def _manifest(
        self,
        *,
        records_seen: int,
        units_emitted: int,
        rejected: int,
        trace_level_fallback: int = 0,
        blocked: bool = False,
        diagnostics: list[Diagnostic] | None = None,
        availability: dict[str, bool] | None = None,
    ) -> SourceImportManifest:
        """Build this connector's coverage manifest (safe identity only — no endpoint/secret)."""
        return SourceImportManifest(
            source=self.lane,
            kind="trace_lane",
            adapter=self.provider,
            data_policy=self._data_policy,
            completeness=derive_completeness(
                records_seen=records_seen,
                units_emitted=units_emitted,
                rejected=rejected,
                trace_level_fallback=trace_level_fallback,
                blocked=blocked,
            ),
            records_seen=records_seen,
            units_emitted=units_emitted,
            rejected=rejected,
            trace_level_fallback=trace_level_fallback,
            endpoint_label=self.endpoint_label,
            availability=availability or {},
            diagnostics=list(diagnostics or []),
            provenance={"provider": self.provider},
        )

    def _diag_read(self, code: str, message: str) -> TraceRead:
        diag = Diagnostic(code=code, severity=Severity.ERROR, message=message, location=self.lane)
        return TraceRead(
            name=self.lane,
            data_policy=self._data_policy,
            units=[],
            diagnostics=[diag],
            # No evidence arrived (egress refused or a fetch fault) → a BLOCKED source manifest.
            manifest=self._manifest(
                records_seen=0, units_emitted=0, rejected=1, blocked=True, diagnostics=[diag]
            ),
        )

    # --- subclass responsibilities -------------------------------------------

    def _default_fetch(self) -> Mapping[str, Any]:  # pragma: no cover - live_lane only
        raise NotImplementedError

    def _to_open_convention(
        self, payload: Mapping[str, Any]
    ) -> tuple[list[Any] | None, list[Diagnostic]]:
        raise NotImplementedError
