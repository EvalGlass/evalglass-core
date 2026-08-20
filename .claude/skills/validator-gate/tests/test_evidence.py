"""Slice 2 (VG-P0-2): evidence-pack reader + source-boundary validator.

Proves the reader keeps Validator durable by reading the declared source
boundary instead of assuming file layout, and fails closed (BLOCKED, i.e.
`not normalized.ok`) when authority direction is missing, unknown,
contradictory, stale, or outside the boundary. Specificity: a well-formed pack
normalizes cleanly and classifies artifacts by authority; an unclassified
artifact that no claim requires is a warning, not a block.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.contracts import (
    ArtifactKind,
    ArtifactRef,
    Authority,
    Claim,
    EvidencePack,
)
from scripts.evidence import (
    EvidenceError,
    NormalizedEvidence,
    load_pack,
    normalize,
    read_evidence,
)

# --- builders ---------------------------------------------------------------


def art(
    art_id: str, authority: Authority, kind: ArtifactKind = ArtifactKind.SCORECARD, **over: object
) -> ArtifactRef:
    return ArtifactRef(id=art_id, kind=kind, authority=authority, **over)  # type: ignore[arg-type]


def claim(claim_id: str = "c1", required: tuple[str, ...] = ()) -> Claim:
    return Claim(id=claim_id, text="claim text", required_artifacts=list(required))


def pack(
    artifacts: list[ArtifactRef],
    boundary: dict[str, list[str]],
    claims: list[Claim],
) -> EvidencePack:
    return EvidencePack(
        checkpoint="EG.step-02.evidence",
        source_boundary=boundary,
        artifacts=artifacts,
        claims=claims,
    )


def valid_pack() -> EvidencePack:
    return pack(
        artifacts=[
            art("scorecard-1", Authority.PRODUCT),
            art("report-1", Authority.EXTERNAL, ArtifactKind.REPORT),
        ],
        boundary={"product": ["scorecard-1"], "external_contracts": ["report-1"]},
        claims=[claim("c1", ("scorecard-1", "report-1"))],
    )


# --- specificity: a clean pack normalizes -----------------------------------


def test_valid_pack_normalizes_and_classifies() -> None:
    n = normalize(valid_pack())
    assert n.ok
    assert n.blocked_on == []
    assert [a.id for a in n.by_authority[Authority.PRODUCT]] == ["scorecard-1"]
    assert [a.id for a in n.by_authority[Authority.EXTERNAL]] == ["report-1"]


def test_classification_by_path_entry() -> None:
    p = pack(
        artifacts=[art("scorecard-1", Authority.PRODUCT, path="evals/reports/sc.json")],
        boundary={"product": ["evals/reports/sc.json"]},
        claims=[claim("c1", ("scorecard-1",))],
    )
    n = normalize(p)
    assert n.ok, n.blocked_on
    assert [a.id for a in n.by_authority[Authority.PRODUCT]] == ["scorecard-1"]


def test_unclassified_but_unrequired_artifact_is_warning_not_block() -> None:
    p = pack(
        artifacts=[
            art("scorecard-1", Authority.PRODUCT),
            art("scratch-1", Authority.GENERATED_OR_PROPOSED),
        ],
        boundary={"product": ["scorecard-1"]},
        claims=[claim("c1", ("scorecard-1",))],
    )
    n = normalize(p)
    assert n.ok, n.blocked_on
    assert any("scratch-1" in w for w in n.warnings)


# --- sensitivity: trust-critical boundary problems block --------------------


def test_missing_source_boundary_blocks() -> None:
    p = pack(artifacts=[art("s1", Authority.PRODUCT)], boundary={}, claims=[claim("c1", ("s1",))])
    n = normalize(p)
    assert not n.ok
    assert any("source" in b.lower() and "boundary" in b.lower() for b in n.blocked_on)


def test_unknown_authority_bucket_blocks() -> None:
    p = pack(
        artifacts=[art("s1", Authority.PRODUCT)],
        boundary={"product": ["s1"], "vendor_lane": ["x"]},
        claims=[claim("c1", ("s1",))],
    )
    n = normalize(p)
    assert not n.ok
    assert any("vendor_lane" in b for b in n.blocked_on)


def test_authority_bucket_mismatch_blocks() -> None:
    # Artifact declares product authority but is listed under the egts bucket.
    p = pack(
        artifacts=[art("s1", Authority.PRODUCT)],
        boundary={"egts": ["s1"]},
        claims=[claim("c1", ("s1",))],
    )
    n = normalize(p)
    assert not n.ok
    assert any("s1" in b and "product" in b and "egts" in b for b in n.blocked_on)


def test_required_artifact_outside_boundary_blocks() -> None:
    # s1 exists but is listed in no bucket; a claim requires it.
    p = pack(
        artifacts=[art("s1", Authority.PRODUCT)],
        boundary={"product": []},
        claims=[claim("c1", ("s1",))],
    )
    n = normalize(p)
    assert not n.ok
    assert any("s1" in b and "boundary" in b.lower() for b in n.blocked_on)


def test_stale_required_artifact_blocks() -> None:
    p = pack(
        artifacts=[art("s1", Authority.PRODUCT, stale=True)],
        boundary={"product": ["s1"]},
        claims=[claim("c1", ("s1",))],
    )
    n = normalize(p)
    assert not n.ok
    assert any("s1" in b and "stale" in b.lower() for b in n.blocked_on)


def test_missing_required_artifact_blocks() -> None:
    p = pack(
        artifacts=[art("s1", Authority.PRODUCT)],
        boundary={"product": ["s1"]},
        claims=[claim("c1", ("s2",))],  # requires an artifact that does not exist
    )
    n = normalize(p)
    assert not n.ok
    assert any("s2" in b for b in n.blocked_on)


def test_same_id_in_two_buckets_is_contradictory_block() -> None:
    p = pack(
        artifacts=[art("s1", Authority.PRODUCT)],
        boundary={"product": ["s1"], "egts": ["s1"]},
        claims=[claim("c1", ("s1",))],
    )
    n = normalize(p)
    assert not n.ok
    assert any("s1" in b for b in n.blocked_on)


# --- loading ----------------------------------------------------------------


def test_load_pack_from_dict() -> None:
    p = load_pack(valid_pack().to_dict())
    assert isinstance(p, EvidencePack)
    assert p.checkpoint == "EG.step-02.evidence"


def test_load_pack_from_file(tmp_path: Path) -> None:
    fp = tmp_path / "pack.json"
    fp.write_text(json.dumps(valid_pack().to_dict()), encoding="utf-8")
    p = load_pack(fp)
    assert isinstance(p, EvidencePack)


def test_load_pack_bad_json_raises_evidence_error(tmp_path: Path) -> None:
    fp = tmp_path / "bad.json"
    fp.write_text("{not json", encoding="utf-8")
    with pytest.raises(EvidenceError):
        load_pack(fp)


def test_load_pack_missing_file_raises_evidence_error(tmp_path: Path) -> None:
    with pytest.raises(EvidenceError):
        load_pack(tmp_path / "nope.json")


def test_load_pack_contract_violation_raises_evidence_error() -> None:
    bad = valid_pack().to_dict()
    del bad["checkpoint"]
    with pytest.raises(EvidenceError):
        load_pack(bad)


@pytest.mark.parametrize(
    "mutation",
    [
        {"source_boundary": None},
        {
            "source_boundary": {"product": "scorecard-1"}
        },  # string, not a list (would shred to chars)
        {"claims": None},
        {"artifacts": None},
    ],
)
def test_load_pack_wrong_typed_fields_raise_evidence_error(mutation: dict[str, object]) -> None:
    bad = {**valid_pack().to_dict(), **mutation}
    with pytest.raises(EvidenceError):
        load_pack(bad)


def test_duplicate_artifact_id_blocks() -> None:
    p = pack(
        artifacts=[
            art("s1", Authority.PRODUCT, stale=True),
            art("s1", Authority.PRODUCT, stale=False),
        ],
        boundary={"product": ["s1"]},
        claims=[claim("c1", ("s1",))],
    )
    n = normalize(p)
    assert not n.ok
    assert any("s1" in b and ("more than once" in b or "ambiguous" in b) for b in n.blocked_on)


def test_read_evidence_is_load_plus_normalize() -> None:
    n = read_evidence(valid_pack().to_dict())
    assert isinstance(n, NormalizedEvidence)
    assert n.ok
