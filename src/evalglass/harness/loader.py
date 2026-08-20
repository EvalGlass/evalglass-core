"""Config file loading — the harness's YAML/filesystem effect boundary (EG-M1-1).

``load_config`` is the only place in slice 1 that reads a file and parses YAML.
Every failure mode (missing file, unreadable file, malformed YAML, invalid schema)
becomes a typed :class:`SetupError` carrying a :class:`~evalglass.core.Diagnostic`,
so the CLI can report it as a setup error with a distinct exit class rather than a
crash or a fake quality verdict (build contract §8). ``yaml.safe_load`` only — never
``load`` (CLAUDE.md §12).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

try:  # PyYAML is the one runtime dependency; a missing install is a setup error, not a crash.
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - exercised via the guard in load_config
    yaml = None

from evalglass.core import ContractError
from evalglass.harness.config import RuntimeConfig
from evalglass.harness.errors import SetupError, setup_diagnostic


def load_config(path: str | Path) -> RuntimeConfig:
    """Read, parse, and validate ``evalglass.yaml`` into a :class:`RuntimeConfig`.

    Raises :class:`SetupError` (never a bare exception) on any setup-phase failure.
    """
    if yaml is None:
        # Fail with the promised typed setup diagnostic + exit 2, not a raw ImportError traceback.
        raise SetupError(
            setup_diagnostic(
                "pyyaml_missing",
                "PyYAML is required to read evalglass.yaml but is not installed; "
                "install it with `pip install pyyaml`.",
            )
        )
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SetupError(
            setup_diagnostic("config_not_found", f"config file not found: {p}", location=str(p))
        ) from exc
    except UnicodeDecodeError as exc:
        # Not an OSError — without this the CLI would surface a traceback instead of
        # the promised setup diagnostic + exit 2 for an undecodable config.
        raise SetupError(
            setup_diagnostic(
                "config_unreadable", f"config file is not valid UTF-8: {p}", location=str(p)
            )
        ) from exc
    except OSError as exc:
        raise SetupError(
            setup_diagnostic("config_unreadable", f"cannot read config {p}: {exc}", location=str(p))
        ) from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SetupError(
            setup_diagnostic("config_parse_error", f"invalid YAML in {p}: {exc}", location=str(p))
        ) from exc

    if not isinstance(data, Mapping):
        kind = type(data).__name__
        raise SetupError(
            setup_diagnostic(
                "config_invalid", f"config root must be a mapping, got {kind}", location=str(p)
            )
        )

    try:
        return RuntimeConfig.from_mapping(data)
    except ContractError as exc:
        raise SetupError(setup_diagnostic("config_invalid", str(exc), location=str(p))) from exc
