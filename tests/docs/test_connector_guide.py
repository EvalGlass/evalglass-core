"""The connector host guide is present and honest (EG-R5-4/EG-R5-5).

Pins the live-connector adoption + privacy/egress/dependency review doc so its trust claims can't
silently drift: it must name all three providers, frame them as opt-in side-channel evidence (never
authority/telemetry/certification), and carry the data-policy + secret guarantees. Test-only.
"""

from __future__ import annotations

import re
from pathlib import Path

_GUIDE = Path(__file__).resolve().parents[2] / "docs" / "CONNECTOR_GUIDE.md"


def _text() -> str:
    return _GUIDE.read_text(encoding="utf-8")


def test_guide_exists_and_names_every_provider() -> None:
    lowered = _text().lower()
    for provider in ("langfuse", "phoenix", "langsmith"):
        assert provider in lowered, f"the connector guide does not name {provider}"


def test_guide_frames_connectors_as_optional_side_channel_evidence() -> None:
    lowered = _text().lower()
    assert "opt-in" in lowered
    assert "optional" in lowered
    assert "lane_results" in _text(), "the guide must explain lane_results as side-channel evidence"
    assert "byte-identical" in lowered, "the guide must tell hosts to compare the verdict payload"
    assert "import evidence, never authority" in lowered


def test_guide_carries_the_privacy_and_egress_guarantees() -> None:
    lowered = _text().lower()
    # Secrets are env-var references, never written to artifacts.
    assert "environment-variable" in lowered
    assert "reference" in lowered
    # Egress-before-effects on a non-egress policy.
    assert "egress" in lowered
    for policy in ("forbidden", "missing", "unknown"):
        assert policy in lowered, f"the guide must name the {policy} data policy"
    # SDKs are isolated optional extras, off the required path; LangChain is never pulled.
    assert "optional extra" in lowered
    assert "langchain" in lowered


def test_guide_does_not_overclaim_telemetry_or_certification() -> None:
    """The doc must explicitly disclaim hosted telemetry / certification, not assert it."""
    # Strip markdown emphasis/code markers and collapse whitespace so a disclaimer that wraps a
    # bolded word ("**not** hosted ... telemetry") still matches as one contiguous claim.
    flat = re.sub(r"\s+", " ", _text().lower().replace("*", "").replace("`", ""))
    assert "not hosted evalglass telemetry" in flat
    assert "certification" in flat  # named only inside the disclaimer below
    assert "not" in flat
    # No bare promotional certification claim (the disclaimer above is the only mention).
    assert "certified" not in flat
