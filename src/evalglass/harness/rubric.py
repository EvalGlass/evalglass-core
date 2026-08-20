"""Host-owned rubric loading + judge provenance (EG-M4-2).

A judge metric scores against a rubric — host-owned truth that lives under ``evals/rubrics/``
(outside the managed ``_evalglass/`` tree). This module loads a declared rubric, fails closed
on a missing / escaping / managed path, and computes a **content fingerprint** so a rubric
edit — even without a version bump — enters the run's gating provenance and breaks baseline
comparability (P14). It owns the file read (an effect); the refs it returns feed the
``JudgeRequest`` and the run fingerprint.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from evalglass.core._validation import ContractError
from evalglass.harness.config import RubricConfig
from evalglass.harness.errors import SetupError, setup_diagnostic
from evalglass.harness.rubric_spec import RubricSpec

_MANAGED_DIR = "_evalglass"


@dataclass(frozen=True)
class RubricRef:
    """A loaded, fingerprinted host-owned rubric — its refs plus a content fingerprint."""

    path: str
    version: str
    prompt_ref: str | None
    model_ref: str | None
    parser_version: str | None
    content_fingerprint: str

    def provenance(self) -> dict[str, Any]:
        """The gating-provenance view: a change to any field breaks comparability."""
        return {
            "rubric": self.path,
            "rubric_version": self.version,
            "prompt_ref": self.prompt_ref,
            "model_ref": self.model_ref,
            "parser_version": self.parser_version,
            "rubric_fingerprint": self.content_fingerprint,
        }


def _resolve_rubric_path(config: RubricConfig, root: Path) -> Path:
    """Validate a host-owned rubric path, failing closed on missing / escaping / managed."""
    rel = PurePosixPath(config.path)
    if rel.is_absolute() or ".." in rel.parts:
        raise SetupError(
            setup_diagnostic(
                "rubric_path_invalid",
                f"rubric path {config.path!r} must be relative and within the host repo",
            )
        )
    if _MANAGED_DIR in rel.parts:
        raise SetupError(
            setup_diagnostic(
                "rubric_path_managed",
                f"rubric {config.path!r} must be host-owned, not under the managed "
                f"{_MANAGED_DIR}/ tree",
            )
        )
    path = root / rel
    if path.is_symlink():
        raise SetupError(
            setup_diagnostic(
                "rubric_path_invalid",
                f"rubric {config.path!r} must be a regular host-owned file, not a symlink",
            )
        )
    if not path.is_file():
        raise SetupError(
            setup_diagnostic("rubric_missing", f"rubric file not found: {config.path}")
        )
    # Resolve symlinks in parent components too: the loaded bytes must live within the host repo
    # and outside the managed tree, so a symlink cannot smuggle in managed/foreign content.
    resolved_root = root.resolve()
    resolved = path.resolve()
    if (
        not resolved.is_relative_to(resolved_root)
        or _MANAGED_DIR in resolved.relative_to(resolved_root).parts
    ):
        raise SetupError(
            setup_diagnostic(
                "rubric_path_invalid",
                f"rubric {config.path!r} resolves outside the host-owned tree",
            )
        )
    return path


def read_rubric_text(config: RubricConfig, root: Path) -> str:
    """Read a host-owned rubric's text (path-safe). The judge scores against this content."""
    path = _resolve_rubric_path(config, root)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SetupError(
            setup_diagnostic("rubric_unreadable", f"could not read rubric {config.path}: {exc}")
        ) from exc


def load_rubric_spec(config: RubricConfig, root: Path) -> RubricSpec:
    """Load a rubric as a structured :class:`RubricSpec`, failing closed on a bad path.

    A ``.json`` rubric is a structured spec (construct + anchored criteria + response schema); any
    other extension (``.md`` …) loads through the scalar compatibility path — an unanchored
    construct with no facets — so existing markdown rubrics and the command judge's score+rationale
    contract keep working. The declared ``version``/``parser_version`` carry into the spec.
    """
    content = read_rubric_text(config, root)
    if config.path.endswith(".json"):
        try:
            data = json.loads(content)
        except ValueError as exc:
            raise SetupError(
                setup_diagnostic(
                    "rubric_invalid", f"structured rubric {config.path} is not valid JSON: {exc}"
                )
            ) from exc
        try:
            return RubricSpec.from_mapping(data, config.path)
        except ContractError as exc:
            raise SetupError(
                setup_diagnostic("rubric_invalid", f"rubric {config.path}: {exc}")
            ) from exc
    return RubricSpec.from_markdown(
        content, version=config.version, parser_version=config.parser_version or "1"
    )


def load_rubric(config: RubricConfig, root: Path) -> RubricRef:
    """Load a host-owned rubric, failing closed on a missing / escaping / managed path."""
    content = read_rubric_text(config, root)
    fingerprint = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
    return RubricRef(
        path=config.path,
        version=config.version,
        prompt_ref=config.prompt_ref,
        model_ref=config.model_ref,
        parser_version=config.parser_version,
        content_fingerprint=fingerprint,
    )
