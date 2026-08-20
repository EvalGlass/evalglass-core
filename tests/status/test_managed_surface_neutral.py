"""Managed-surface neutrality guard (EG-NR-10).

EvalGlass is generic by contract: no knowledge of any specific host application or domain may enter
a *shipped* surface — the managed runtime (``src/evalglass``), the agent-facing ``skills/``, or the
worked ``examples/``. A shipped skill biases what an agent proposes; a shipped fixture defines what
contributors normalize as "ordinary". Field evaluations run against real (sometimes domain-specific)
apps, but that domain must stay in the host's own ``evals/`` tree.

This guard targets a *deliberately narrow* list of distinctive host identifiers — the kind of
app-specific codename, model code, or acronym that can leak from a field evaluation and could not
appear by coincidence in a generic framework — not vocabulary by association. Ordinary words
("agent", "incident", "classification", "defense in depth") are explicitly allowed. The tokens below
are **fictional placeholders** standing in for that shape; real, sensitive host identifiers are
never committed to this repo.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Shipped surfaces a plugin user or coding agent actually sees. Test and roadmap trees are excluded
#: on purpose — they may cite a field run as historical evidence; shipped surfaces may not.
_SHIPPED_DIRS = ("src/evalglass", "skills", "examples")

_TEXT_SUFFIXES = {".py", ".md", ".json", ".yaml", ".yml", ".txt", ".toml", ".cfg"}

#: Distinctive host identifiers of the shape that must never reach a shipped surface — a codename,
#: a model/unit code, a program acronym, a distinctive phrase. Kept specific enough that a substring
#: match cannot be an ordinary English/framework word. Matched case-insensitively. These are
#: fictional placeholders; a real, sensitive identifier is added only to a local, unshipped copy.
_BANNED = (
    "Quorvex",
    "Acmetron",
    "ZX-9",
    "GLIMWICK",
    "Vantablox",
    "widgetflux",
    "meridian-lattice",
)

_PATTERN = re.compile("|".join(re.escape(tok) for tok in _BANNED), re.IGNORECASE)


def _shipped_files() -> list[Path]:
    files: list[Path] = []
    for rel in _SHIPPED_DIRS:
        root = _REPO_ROOT / rel
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in _TEXT_SUFFIXES:
                continue
            if "__pycache__" in path.parts:
                continue
            files.append(path)
    return files


def _leaks(text: str) -> list[str]:
    return sorted({m.group(0) for m in _PATTERN.finditer(text)})


def test_shipped_surfaces_carry_no_host_identifier() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _shipped_files():
        found = _leaks(path.read_text(encoding="utf-8", errors="ignore"))
        if found:
            offenders[str(path.relative_to(_REPO_ROOT))] = found
    assert not offenders, (
        "host-specific identifiers leaked into a shipped surface (src/skills/examples); "
        f"genericise them (EG-NR-10): {offenders}"
    )


def test_guard_has_sensitivity() -> None:
    # A planted host identifier must be caught (else the guard proves nothing).
    assert _leaks("the GLIMWICK analysis output") == ["GLIMWICK"]
    assert _leaks("classified as ZX-9") == ["ZX-9"]


@pytest.mark.parametrize(
    "ordinary",
    [
        "the agent classified the incident by category",
        "defense in depth keeps the gate fail-closed",
        "known threats to construct validity are listed in the ClaimSpec",
        "extract records from the source document",
    ],
)
def test_guard_has_specificity(ordinary: str) -> None:
    # Ordinary framework/English vocabulary must NOT be flagged.
    assert _leaks(ordinary) == []
