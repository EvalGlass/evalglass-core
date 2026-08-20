"""Slice 3 (VG-P0-3): claim/artifact evidence index.

Proves families can query evidence without re-parsing the pack: lookups by id,
authority, and kind; a claim's required artifacts resolved to refs; missing
required artifacts visible *before* family validation; claims grouped by their
expected family; and artifact lineage (claim_ids, produced_by) preserved for
findings. The index also fails closed on empty claim id/text, and its lookups
are deterministic for replay.
"""

from __future__ import annotations

from scripts.contracts import ArtifactKind, ArtifactRef, Authority, Claim, EvidencePack, FamilyId
from scripts.evidence import normalize
from scripts.index import EvidenceIndex

# --- builders ---------------------------------------------------------------


def art(
    art_id: str, authority: Authority, kind: ArtifactKind = ArtifactKind.SCORECARD, **over: object
) -> ArtifactRef:
    return ArtifactRef(id=art_id, kind=kind, authority=authority, **over)  # type: ignore[arg-type]


def claim(
    claim_id: str, required: tuple[str, ...] = (), families: tuple[FamilyId, ...] = ()
) -> Claim:
    return Claim(
        id=claim_id,
        text=f"text for {claim_id}",
        required_artifacts=list(required),
        expected_families=list(families),
    )


def pack(
    artifacts: list[ArtifactRef], boundary: dict[str, list[str]], claims: list[Claim]
) -> EvidencePack:
    return EvidencePack(
        checkpoint="EG.step-03.index", source_boundary=boundary, artifacts=artifacts, claims=claims
    )


# Every authority -> its boundary bucket name (external uses external_contracts).
AUTH_BUCKET = {
    Authority.PRODUCT: "product",
    Authority.EGTS: "egts",
    Authority.EXECUTION_LOOP: "execution_loop",
    Authority.SCAN_GATE: "scan_gate",
    Authority.VALIDATOR_GATE: "validator_gate",
    Authority.GENERATED_OR_PROPOSED: "generated_or_proposed",
    Authority.EXTERNAL: "external_contracts",
}


# --- build / lookups --------------------------------------------------------


def test_build_from_pack_and_dict_and_normalized() -> None:
    p = pack([art("a1", Authority.PRODUCT)], {"product": ["a1"]}, [claim("c1", ("a1",))])
    assert EvidenceIndex.build(p).ok
    assert EvidenceIndex.build(p.to_dict()).ok
    assert EvidenceIndex.build(normalize(p)).ok


def test_lookup_across_all_seven_authorities() -> None:
    artifacts = [art(f"art-{a.value}", a) for a in Authority]
    boundary = {AUTH_BUCKET[a]: [f"art-{a.value}"] for a in Authority}
    idx = EvidenceIndex.build(pack(artifacts, boundary, [claim("c1")]))
    assert idx.ok, idx.blocked_on
    for a in Authority:
        found = idx.artifacts_by_authority(a)
        assert [x.id for x in found] == [f"art-{a.value}"], a


def test_lookup_by_kind() -> None:
    idx = EvidenceIndex.build(
        pack(
            [
                art("sc", Authority.PRODUCT, ArtifactKind.SCORECARD),
                art("rep", Authority.EXTERNAL, ArtifactKind.REPORT),
            ],
            {"product": ["sc"], "external_contracts": ["rep"]},
            [claim("c1")],
        )
    )
    assert [a.id for a in idx.artifacts_by_kind(ArtifactKind.REPORT)] == ["rep"]


def test_multi_artifact_claim_resolves_required() -> None:
    idx = EvidenceIndex.build(
        pack(
            [art("a", Authority.PRODUCT), art("b", Authority.EXTERNAL, ArtifactKind.REPORT)],
            {"product": ["a"], "external_contracts": ["b"]},
            [claim("c1", ("a", "b"))],
        )
    )
    assert [a.id for a in idx.required_artifacts("c1")] == ["a", "b"]
    assert idx.missing_artifacts("c1") == []


def test_multi_claim_artifact_shared() -> None:
    shared = art("shared", Authority.PRODUCT, claim_ids=["c1", "c2"], produced_by="evalglass")
    idx = EvidenceIndex.build(
        pack(
            [shared], {"product": ["shared"]}, [claim("c1", ("shared",)), claim("c2", ("shared",))]
        )
    )
    assert idx.artifact("shared") is not None
    assert [a.id for a in idx.required_artifacts("c1")] == ["shared"]
    assert [a.id for a in idx.required_artifacts("c2")] == ["shared"]
    # lineage preserved for findings
    assert idx.artifact("shared").claim_ids == ["c1", "c2"]
    assert idx.artifact("shared").produced_by == "evalglass"


def test_missing_required_artifact_is_visible() -> None:
    idx = EvidenceIndex.build(
        pack([art("a", Authority.PRODUCT)], {"product": ["a"]}, [claim("c1", ("a", "absent"))])
    )
    assert idx.missing_artifacts("c1") == ["absent"]


def test_claims_for_family() -> None:
    idx = EvidenceIndex.build(
        pack(
            [art("a", Authority.PRODUCT)],
            {"product": ["a"]},
            [
                claim("c1", ("a",), (FamilyId.AUTHORITY_VERDICT,)),
                claim("c2", ("a",), (FamilyId.CONTRACT_BOUNDARY, FamilyId.AUTHORITY_VERDICT)),
                claim("c3", ("a",), (FamilyId.CONTRACT_BOUNDARY,)),
            ],
        )
    )
    assert {c.id for c in idx.claims_for_family(FamilyId.AUTHORITY_VERDICT)} == {"c1", "c2"}
    assert {c.id for c in idx.claims_for_family(FamilyId.CONTRACT_BOUNDARY)} == {"c2", "c3"}


def test_artifact_resolves_by_path() -> None:
    idx = EvidenceIndex.build(
        pack(
            [art("a1", Authority.PRODUCT, path="evals/x.json")],
            {"product": ["a1"]},
            [claim("c1", ("evals/x.json",))],
        )
    )
    assert idx.artifact("evals/x.json") is not None
    assert [a.id for a in idx.required_artifacts("c1")] == ["a1"]


# --- fail closed on bad claims ----------------------------------------------


def test_empty_claim_id_blocks() -> None:
    idx = EvidenceIndex.build(
        pack([art("a", Authority.PRODUCT)], {"product": ["a"]}, [claim("", ("a",))])
    )
    assert not idx.ok
    assert any("id" in b.lower() for b in idx.blocked_on)


def test_empty_claim_text_blocks() -> None:
    bad = Claim(id="c1", text="   ", required_artifacts=["a"])
    idx = EvidenceIndex.build(pack([art("a", Authority.PRODUCT)], {"product": ["a"]}, [bad]))
    assert not idx.ok
    assert any("text" in b.lower() for b in idx.blocked_on)


def test_duplicate_claim_id_blocks() -> None:
    p = pack(
        [art("a", Authority.PRODUCT)],
        {"product": ["a"]},
        [claim("dup", ("a",)), claim("dup", ("a",))],
    )
    idx = EvidenceIndex.build(p)
    assert not idx.ok
    assert any("dup" in b and ("more than once" in b or "ambiguous" in b) for b in idx.blocked_on)


def test_non_string_claim_fields_fail_closed() -> None:
    # Build from a raw dict with a non-string claim id/text: the contract layer
    # rejects it (fail closed) rather than crashing on .strip() in the index.
    from scripts.evidence import EvidenceError

    base = pack([art("a", Authority.PRODUCT)], {"product": ["a"]}, [claim("c1", ("a",))]).to_dict()
    for bad_claim in ({"id": 1, "text": "t"}, {"id": "c1", "text": None}):
        mutated = {**base, "claims": [bad_claim]}
        try:
            idx = EvidenceIndex.build(mutated)
        except EvidenceError:
            continue  # rejected at the contract layer — acceptable fail-closed
        assert not idx.ok  # otherwise it must at least be BLOCKED


def test_evidence_blocks_propagate() -> None:
    # An evidence-level block (missing boundary) is carried by the index too.
    idx = EvidenceIndex.build(pack([art("a", Authority.PRODUCT)], {}, [claim("c1", ("a",))]))
    assert not idx.ok


# --- determinism ------------------------------------------------------------


def test_lookups_are_deterministic() -> None:
    p = pack(
        [
            art("a", Authority.PRODUCT),
            art("b", Authority.PRODUCT),
            art("c", Authority.EXTERNAL, ArtifactKind.REPORT),
        ],
        {"product": ["a", "b"], "external_contracts": ["c"]},
        [claim("c1", ("a", "b", "c"))],
    )
    one = EvidenceIndex.build(p)
    two = EvidenceIndex.build(p)
    assert [x.id for x in one.artifacts_by_authority(Authority.PRODUCT)] == [
        x.id for x in two.artifacts_by_authority(Authority.PRODUCT)
    ]
    assert [x.id for x in one.required_artifacts("c1")] == [
        x.id for x in two.required_artifacts("c1")
    ]
