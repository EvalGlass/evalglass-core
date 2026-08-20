"""Fail-closed loader for the companion ontology artifact (EG-AT5-1; plan §D Part 2, Appendix B).

Track A parses + structurally validates the artifact **exactly as it exists** — it makes no claim
of live-code equivalence (that is Track B, EG-AT5-3+). The validation mirrors the artifact's own
``evalglass-ontology.schema.json`` structural rules (required keys, the ``^prefix.suffix`` id
pattern, the closed ``status`` / ``verification`` vocabularies, unique ids) using the standard
library only — no ``jsonschema`` dependency is added to the framework.

Artifact resolution (first hit wins): the ``EVALGLASS_ONTOLOGY`` env var, then the in-repo vendored
copy under ``docs/design/ontology/``. When neither is present, ``artifact_path()`` returns ``None``
so callers can skip-with-count rather than silently pass over zero entities (plan §3.1, GAP P1-2).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ID_RE = re.compile(r"^[a-z]+\.[a-z0-9.-]+$")
_STATUS = frozenset({"now", "next", "planned", "experimental"})
_VERIFICATION = frozenset({"asserted", "conceptual"})
_TOP_REQUIRED = ("ontology", "version", "about", "meta", "stats", "entities", "relations")
_META_REQUIRED = ("classes", "predicates", "status", "verification", "idScheme")
_STATS_REQUIRED = ("entities", "relations", "byClass")
_ENTITY_REQUIRED = ("id", "class", "label", "definition", "status", "verification", "evidence")
_RELATION_REQUIRED = ("predicate", "from", "to")

#: In-repo vendored copy of the artifact, kept in sync with the sibling site repo.
REPO_ARTIFACT = (
    Path(__file__).resolve().parents[2] / "docs" / "design" / "ontology" / "evalglass-ontology.json"
)


class OntologyError(ValueError):
    """Raised when the ontology artifact is structurally invalid (fail closed)."""


@dataclass(frozen=True)
class Entity:
    """One ontology entity (a node in the graph)."""

    id: str
    cls: str
    label: str
    definition: str
    status: str
    verification: str
    kind: str | None
    repo_locator: str | None
    evidence: tuple[str, ...]
    notes: str | None


@dataclass(frozen=True)
class Relation:
    """One directed ontology relation (a typed edge)."""

    predicate: str
    src: str
    dst: str


@dataclass(frozen=True)
class Ontology:
    """A parsed, structurally-valid ontology."""

    entities: tuple[Entity, ...]
    relations: tuple[Relation, ...]
    meta: Mapping[str, Any]
    stats: Mapping[str, Any]

    def entity_ids(self) -> set[str]:
        return {e.id for e in self.entities}

    def by_class(self, cls: str) -> list[Entity]:
        return [e for e in self.entities if e.cls == cls]


def _require(obj: Mapping[str, Any], keys: Sequence[str], ctx: str) -> None:
    missing = [k for k in keys if k not in obj]
    if missing:
        raise OntologyError(f"{ctx}: missing required key(s): {missing}")


def _str(obj: Mapping[str, Any], key: str, ctx: str, *, min_len: int = 1) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or len(value) < min_len:
        raise OntologyError(
            f"{ctx}: {key!r} must be a string of length >= {min_len}, got {value!r}"
        )
    return value


def _parse_entity(raw: Any, ctx: str) -> Entity:
    if not isinstance(raw, Mapping):
        raise OntologyError(f"{ctx}: entity must be an object, got {type(raw).__name__}")
    _require(raw, _ENTITY_REQUIRED, ctx)
    ident = _str(raw, "id", ctx)
    if not _ID_RE.match(ident):
        raise OntologyError(f"{ctx}: id {ident!r} does not match the ^prefix.suffix scheme")
    status = _str(raw, "status", ctx)
    if status not in _STATUS:
        raise OntologyError(f"{ctx} ({ident}): status {status!r} not in {sorted(_STATUS)}")
    verification = _str(raw, "verification", ctx)
    if verification not in _VERIFICATION:
        raise OntologyError(f"{ctx} ({ident}): verification {verification!r} is not a known value")
    evidence = raw.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise OntologyError(f"{ctx} ({ident}): 'evidence' must be a non-empty list")
    if not all(isinstance(item, str) for item in evidence):
        raise OntologyError(f"{ctx} ({ident}): every evidence entry must be a string")
    if not all(item.startswith("/") for item in evidence):
        raise OntologyError(f"{ctx} ({ident}): every evidence locator must start with '/'")
    return Entity(
        id=ident,
        cls=_str(raw, "class", ctx),
        label=_str(raw, "label", ctx),
        definition=_str(raw, "definition", ctx, min_len=10),
        status=status,
        verification=verification,
        kind=raw.get("kind"),
        repo_locator=raw.get("repoLocator"),
        evidence=tuple(evidence),
        notes=raw.get("notes"),
    )


def _parse_relation(raw: Any, ctx: str) -> Relation:
    if not isinstance(raw, Mapping):
        raise OntologyError(f"{ctx}: relation must be an object, got {type(raw).__name__}")
    _require(raw, _RELATION_REQUIRED, ctx)
    return Relation(
        predicate=_str(raw, "predicate", ctx),
        src=_str(raw, "from", ctx),
        dst=_str(raw, "to", ctx),
    )


def parse_ontology(data: Any) -> Ontology:
    """Validate + parse a decoded ontology document, failing closed on any structural defect."""
    if not isinstance(data, Mapping):
        raise OntologyError("ontology root must be a JSON object")
    _require(data, _TOP_REQUIRED, "ontology")
    if data.get("ontology") != "evalglass":
        raise OntologyError(
            f"ontology: 'ontology' must be 'evalglass', got {data.get('ontology')!r}"
        )
    meta = data["meta"]
    if not isinstance(meta, Mapping):
        raise OntologyError("ontology.meta must be an object")
    _require(meta, _META_REQUIRED, "ontology.meta")
    if not isinstance(meta["classes"], Mapping) or not meta["classes"]:
        raise OntologyError("ontology.meta.classes must be a non-empty object")
    if not isinstance(meta["predicates"], Mapping) or not meta["predicates"]:
        raise OntologyError("ontology.meta.predicates must be a non-empty object")
    stats = data["stats"]
    if not isinstance(stats, Mapping):
        raise OntologyError("ontology.stats must be an object")
    _require(stats, _STATS_REQUIRED, "ontology.stats")

    raw_entities = data["entities"]
    raw_relations = data["relations"]
    if not isinstance(raw_entities, list) or not raw_entities:
        raise OntologyError("ontology.entities must be a non-empty list")
    if not isinstance(raw_relations, list) or not raw_relations:
        raise OntologyError("ontology.relations must be a non-empty list")

    entities = tuple(_parse_entity(e, f"entities[{i}]") for i, e in enumerate(raw_entities))
    seen: set[str] = set()
    for entity in entities:
        if entity.id in seen:
            raise OntologyError(f"duplicate entity id {entity.id!r}")
        seen.add(entity.id)
    relations = tuple(_parse_relation(r, f"relations[{i}]") for i, r in enumerate(raw_relations))
    # Graph integrity: every relation names a known predicate and resolves both endpoints.
    predicate_vocab = set(meta["predicates"].keys())
    for i, rel in enumerate(relations):
        if rel.predicate not in predicate_vocab:
            raise OntologyError(f"relations[{i}]: unknown predicate {rel.predicate!r}")
        for role, endpoint in (("from", rel.src), ("to", rel.dst)):
            if endpoint not in seen:
                raise OntologyError(
                    f"relations[{i}]: {role} endpoint {endpoint!r} is not a known entity id"
                )
    return Ontology(entities=entities, relations=relations, meta=meta, stats=stats)


def load_ontology(path: Path | str) -> Ontology:
    """Read + parse an ontology JSON file (fail closed on malformed JSON or structure)."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OntologyError(f"{path}: not valid JSON: {exc}") from exc
    return parse_ontology(data)


def artifact_path() -> Path | None:
    """Resolve the real artifact path (env override, then in-repo copy); ``None`` if unavailable."""
    env = os.environ.get("EVALGLASS_ONTOLOGY")
    if env:
        candidate = Path(env)
        return candidate if candidate.is_file() else None
    return REPO_ARTIFACT if REPO_ARTIFACT.is_file() else None


def load_real_ontology() -> Ontology | None:
    """Load the real artifact, or ``None`` when no artifact path is available (skip-with-count)."""
    path = artifact_path()
    return load_ontology(path) if path is not None else None
