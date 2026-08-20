"""Slice 10 (VG-P1-6): integration_boundary family.

Optional stays optional; hidden inputs cannot back controlled claims. Content
conventions on integration artifacts: ``lane`` (name) + ``optional`` /
``required`` / ``treated_as_required``; ``influences_verdict`` +
``declared_boundary`` (judge/RAG); ``vendored``/``copied`` + ``treated_as_original``;
``hidden_input``.

- FAIL: optional lane treated as required; judge/RAG influence without a declared
  boundary; vendored/copied material treated as original product evidence; a
  hidden input backing a controlled/reproducible claim.
- BLOCKED: no evidence; a lane with undeclared optionality; an integration claim
  with no integration artifact.
- PASS: a declared-optional lane not required by the claim; declared boundaries.
"""

from __future__ import annotations

from scripts.contracts import (
    ArtifactKind,
    ArtifactRef,
    Authority,
    Claim,
    EvidencePack,
    FamilyId,
    Status,
)
from scripts.families.base import FamilyContext
from scripts.families.integration_boundary import validate
from scripts.index import EvidenceIndex
from scripts.runner import run_validation

BUCKET = {Authority.EXTERNAL: "external_contracts", Authority.PRODUCT: "product"}


def art(art_id, authority=Authority.EXTERNAL, kind=ArtifactKind.TRACE, content=None) -> ArtifactRef:
    return ArtifactRef(id=art_id, kind=kind, authority=authority, content=content)


def ctx_for(artifacts, required, surfaces=()) -> FamilyContext:
    boundary: dict[str, list[str]] = {}
    for a in artifacts:
        boundary.setdefault(BUCKET[a.authority], []).append(a.id)
    claim = Claim(
        id="c1",
        text="optional integrations stay optional and bounded",
        expected_families=[FamilyId.INTEGRATION_BOUNDARY],
        risk_surfaces=list(surfaces),
        required_artifacts=required,
    )
    pack = EvidencePack(
        checkpoint="cp", source_boundary=boundary, artifacts=artifacts, claims=[claim]
    )
    index = EvidenceIndex.build(pack)
    assert index.ok, index.blocked_on
    return FamilyContext(index=index, claim=claim)


def only(findings):
    assert len(findings) == 1
    return findings[0]


# --- specificity (PASS) -----------------------------------------------------


def test_declared_optional_lane_passes() -> None:
    arts = [art("phoenix", content={"lane": "phoenix", "optional": True})]
    assert (
        only(validate(ctx_for(arts, ["phoenix"], surfaces=("optional_lane",)))).status
        is Status.PASS
    )


def test_judge_with_declared_boundary_passes() -> None:
    arts = [art("judge", content={"influences_verdict": True, "declared_boundary": True})]
    assert (
        only(validate(ctx_for(arts, ["judge"], surfaces=("external_judge",)))).status is Status.PASS
    )


# --- sensitivity (FAIL) -----------------------------------------------------


def test_optional_lane_treated_as_required_fails() -> None:
    arts = [art("lane", content={"lane": "ragas", "optional": True, "treated_as_required": True})]
    f = only(validate(ctx_for(arts, ["lane"], surfaces=("optional_lane",))))
    assert f.status is Status.FAIL
    assert "lane" in f.evidence_refs


def test_judge_influence_without_boundary_fails() -> None:
    arts = [art("judge", content={"influences_verdict": True})]
    assert (
        only(validate(ctx_for(arts, ["judge"], surfaces=("external_judge",)))).status is Status.FAIL
    )


def test_vendored_treated_as_original_fails() -> None:
    arts = [art("vend", content={"vendored": True, "treated_as_original": True})]
    f = only(validate(ctx_for(arts, ["vend"], surfaces=("vendoring",))))
    assert f.status is Status.FAIL


def test_hidden_input_backing_reproducible_claim_fails() -> None:
    arts = [art("route", content={"runtime_route": "x", "hidden_input": True})]
    f = only(validate(ctx_for(arts, ["route"], surfaces=("reproducibility",))))
    assert f.status is Status.FAIL


# --- vendoring manifest/lock evidence (M3 finding) --------------------------


def test_manifest_lock_vendoring_evidence_recognized_and_passes() -> None:
    # The real EvalGlass vendoring evidence: a manifest (managed_root,
    # all_under_managed_root) + lock (skill_vendored). These must be recognized
    # as integration evidence WITHOUT a synthetic `lane` marker, and pass when
    # the vendored runtime is bounded to the managed root.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"managed_root": "evals/_evalglass", "all_under_managed_root": True},
        ),
        art(
            "lock",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"installed_features": ["core", "harness"], "skill_vendored": True},
        ),
    ]
    f = only(validate(ctx_for(arts, ["manifest", "lock"], surfaces=("integration",))))
    assert f.status is Status.PASS


def test_summary_artifact_with_managed_root_does_not_mask_manifest_proof() -> None:
    # A realistic pack: the vendor manifest proves boundedness via files, while
    # an InstallPlan / install summary also carries `managed_root` but no files.
    # The summary's lack of self-proof must not BLOCK a claim the manifest proves.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {
                "managed_root": "evals/_evalglass",
                "files": [{"path": "evals/_evalglass/core.py", "sha256": "a"}],
            },
        ),
        art(
            "install_plan",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"managed_root": "evals/_evalglass", "installed_features": ["core"]},
        ),
        art(
            "lock",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"skill_vendored": True},
        ),
    ]
    f = only(
        validate(ctx_for(arts, ["manifest", "install_plan", "lock"], surfaces=("integration",)))
    )
    assert f.status is Status.PASS


def test_managed_material_not_bounded_fails() -> None:
    # all_under_managed_root: false means managed material leaks outside the
    # managed root -> the vendored runtime is not bounded.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"managed_root": "evals/_evalglass", "all_under_managed_root": False},
        ),
    ]
    f = only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",))))
    assert f.status is Status.FAIL
    assert "manifest" in f.evidence_refs


def test_real_manifest_files_all_under_root_passes() -> None:
    # The real VendorManifest shape (managed_root + files records, no summary
    # boolean): boundedness is DERIVED from the file paths.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {
                "managed_root": "evals/_evalglass",
                "files": [
                    {"path": "evals/_evalglass/core.py", "sha256": "a"},
                    {"path": "evals/_evalglass/harness/cli.py", "sha256": "b"},
                ],
            },
        ),
    ]
    assert (
        only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",)))).status is Status.PASS
    )


def test_real_manifest_with_out_of_root_file_fails() -> None:
    # A managed file outside the managed root is a leak -> not bounded.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {
                "managed_root": "evals/_evalglass",
                "files": [{"path": "evals/host-owned.py", "sha256": "x"}],
            },
        ),
    ]
    f = only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",))))
    assert f.status is Status.FAIL
    assert "manifest" in f.evidence_refs


def test_manifest_without_boundedness_proof_blocks() -> None:
    # managed_root claimed but no all_under_managed_root flag and no files -> fail closed.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"managed_root": "evals/_evalglass"},
        )
    ]
    assert (
        only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",)))).status
        is Status.BLOCKED
    )


def test_escaping_dotdot_path_fails() -> None:
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {
                "managed_root": "evals/_evalglass",
                "files": [{"path": "evals/_evalglass/../host-owned.py", "sha256": "x"}],
            },
        )
    ]
    assert (
        only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",)))).status is Status.FAIL
    )


def test_contradictory_summary_does_not_mask_leaking_file() -> None:
    # all_under_managed_root: true but a record escapes -> concrete records win.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {
                "managed_root": "evals/_evalglass",
                "all_under_managed_root": True,
                "files": [{"path": "evals/host-owned.py", "sha256": "x"}],
            },
        )
    ]
    assert (
        only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",)))).status is Status.FAIL
    )


def test_explicit_false_summary_overrides_clean_records() -> None:
    # all_under_managed_root: false asserts a leak; clean-looking records must
    # not flip it to PASS -> fail closed.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {
                "managed_root": "evals/_evalglass",
                "all_under_managed_root": False,
                "files": [{"path": "evals/_evalglass/core.py", "sha256": "a"}],
            },
        )
    ]
    f = only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",))))
    assert f.status is Status.FAIL
    assert "manifest" in f.evidence_refs


def test_malformed_managed_root_with_leaking_files_blocks() -> None:
    # A malformed managed_root (non-string) still marks the artifact as a
    # boundedness claim; it cannot be proven bounded -> fail closed, never PASS.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"managed_root": 123, "files": [{"path": "evals/host-owned.py", "sha256": "x"}]},
        )
    ]
    assert (
        only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",)))).status
        is Status.BLOCKED
    )


def test_malformed_summary_without_root_blocks() -> None:
    # all_under_managed_root with a non-bool value and no root is malformed.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"all_under_managed_root": "yes"},
        )
    ]
    assert (
        only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",)))).status
        is Status.BLOCKED
    )


def test_malformed_files_shape_not_masked_by_summary_blocks() -> None:
    # all_under_managed_root: true must not mask a malformed `files` (wrong JSON
    # shape) -> the records are present but unprovable -> fail closed.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {
                "managed_root": "evals/_evalglass",
                "all_under_managed_root": True,
                "files": {"path": "evals/host-owned.py"},
            },
        )
    ]
    assert (
        only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",)))).status
        is Status.BLOCKED
    )


def test_blank_root_with_summary_blocks() -> None:
    # An empty managed_root cannot bound anything; a summary flag must not turn
    # it into a PASS.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"managed_root": "", "all_under_managed_root": True},
        )
    ]
    assert (
        only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",)))).status
        is Status.BLOCKED
    )


def test_root_slash_with_summary_blocks() -> None:
    # A bare "/" root bounds the whole tree -> not a real boundary.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"managed_root": "/", "all_under_managed_root": True},
        )
    ]
    assert (
        only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",)))).status
        is Status.BLOCKED
    )


def test_record_missing_path_blocks_not_fails() -> None:
    # A record with no usable string path is malformed evidence, not a proven
    # leak -> BLOCKED (unproven), not FAIL.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"managed_root": "evals/_evalglass", "files": [{"sha256": "x"}]},
        )
    ]
    assert (
        only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",)))).status
        is Status.BLOCKED
    )


def test_dot_root_with_summary_blocks() -> None:
    # "." / "./" bound the whole repository, not a managed subtree -> fail closed.
    for root in (".", "./"):
        arts = [
            art(
                "manifest",
                Authority.PRODUCT,
                ArtifactKind.PROVENANCE,
                {"managed_root": root, "all_under_managed_root": True},
            )
        ]
        assert (
            only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",)))).status
            is Status.BLOCKED
        ), root


def test_generic_files_on_unrelated_artifact_does_not_block() -> None:
    # A declared-optional lane plus an unrelated artifact that merely has a
    # generic `files` array (no managed_root) must still PASS — `files` alone is
    # not a vendoring boundary claim.
    arts = [
        art("phoenix", content={"lane": "phoenix", "optional": True}),
        art(
            "review",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"files": [{"path": "anything.py"}]},
        ),
    ]
    assert (
        only(validate(ctx_for(arts, ["phoenix", "review"], surfaces=("optional_lane",)))).status
        is Status.PASS
    )


def test_leak_outranks_malformed_record_regardless_of_order() -> None:
    # A malformed record before a proven out-of-root leak must still surface the
    # leak as FAIL, not BLOCK -> order-independent.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {
                "managed_root": "evals/_evalglass",
                "files": [{"sha256": "x"}, {"path": "evals/host-owned.py"}],
            },
        )
    ]
    f = only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",))))
    assert f.status is Status.FAIL
    assert "manifest" in f.evidence_refs


def test_record_equal_to_root_blocks_not_passes() -> None:
    # A file record equal to the managed root dir proves no file under the
    # subtree -> unproven, not bounded.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"managed_root": "evals/_evalglass", "files": ["evals/_evalglass"]},
        )
    ]
    assert (
        only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",)))).status
        is Status.BLOCKED
    )


def test_record_root_with_trailing_slash_blocks() -> None:
    # The managed root dir with a trailing slash proves no file beneath it.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"managed_root": "evals/_evalglass", "files": ["evals/_evalglass/"]},
        )
    ]
    assert (
        only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",)))).status
        is Status.BLOCKED
    )


def test_whitespace_prefixed_record_path_is_not_normalized_to_pass() -> None:
    # A leading-whitespace record path is exact evidence of an out-of-root file;
    # it must not be trimmed into a bounded PASS.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"managed_root": "evals/_evalglass", "files": [{"path": " evals/_evalglass/core.py"}]},
        )
    ]
    assert (
        only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",)))).status is Status.FAIL
    )


def test_whitespace_prefixed_managed_root_blocks() -> None:
    # A managed_root with surrounding whitespace is malformed -> fail closed.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"managed_root": " evals/_evalglass", "all_under_managed_root": True},
        )
    ]
    assert (
        only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",)))).status
        is Status.BLOCKED
    )


def test_empty_files_without_summary_blocks() -> None:
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"managed_root": "evals/_evalglass", "files": []},
        )
    ]
    assert (
        only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",)))).status
        is Status.BLOCKED
    )


def test_lock_only_vendoring_without_bounded_manifest_blocks() -> None:
    # skill_vendored asserted but no manifest proving boundedness -> fail closed.
    arts = [
        art(
            "lock",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"installed_features": ["core"], "skill_vendored": True},
        )
    ]
    assert only(validate(ctx_for(arts, ["lock"], surfaces=("vendoring",)))).status is Status.BLOCKED


def test_summary_false_without_root_fails() -> None:
    # all_under_managed_root: false with no managed_root still asserts material
    # outside an implied root -> must not fall through to PASS.
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"all_under_managed_root": False},
        )
    ]
    f = only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",))))
    assert f.status is Status.FAIL


def test_summary_true_without_root_blocks() -> None:
    # all_under_managed_root: true but no managed_root is malformed (bounded to
    # what?) -> fail closed.
    arts = [
        art(
            "manifest", Authority.PRODUCT, ArtifactKind.PROVENANCE, {"all_under_managed_root": True}
        )
    ]
    assert (
        only(validate(ctx_for(arts, ["manifest"], surfaces=("integration",)))).status
        is Status.BLOCKED
    )


def test_copied_with_declared_separation_passes() -> None:
    # Copied material with declared product separation (treated_as_original:
    # false) and no managed root must not be forced to provide a vendored-runtime
    # manifest.
    arts = [
        art(
            "copy",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"copied": True, "treated_as_original": False},
        )
    ]
    assert only(validate(ctx_for(arts, ["copy"], surfaces=("vendoring",)))).status is Status.PASS


def test_unproven_manifest_does_not_mask_proven_fail() -> None:
    # A pack with an unproven manifest AND an independently-failing optional lane
    # must surface the FAIL, not the fail-closed BLOCKED (FAIL > BLOCKED).
    arts = [
        art(
            "manifest",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"managed_root": "evals/_evalglass"},
        ),
        art("lane", content={"lane": "ragas", "optional": True, "treated_as_required": True}),
    ]
    f = only(
        validate(ctx_for(arts, ["manifest", "lane"], surfaces=("integration", "optional_lane")))
    )
    assert f.status is Status.FAIL
    assert "lane" in f.evidence_refs


def test_skill_vendored_treated_as_original_fails() -> None:
    arts = [
        art(
            "lock",
            Authority.PRODUCT,
            ArtifactKind.PROVENANCE,
            {"skill_vendored": True, "treated_as_original": True},
        )
    ]
    f = only(validate(ctx_for(arts, ["lock"], surfaces=("vendoring",))))
    assert f.status is Status.FAIL


# --- BLOCKED ----------------------------------------------------------------


def test_lane_with_undeclared_optionality_blocks() -> None:
    arts = [art("lane", content={"lane": "x"})]  # neither optional nor required declared
    assert (
        only(validate(ctx_for(arts, ["lane"], surfaces=("optional_lane",)))).status
        is Status.BLOCKED
    )


def test_integration_surface_without_integration_artifact_blocks() -> None:
    arts = [art("sc", Authority.PRODUCT, ArtifactKind.SCORECARD, {"verdict": "pass"})]
    assert (
        only(validate(ctx_for(arts, ["sc"], surfaces=("optional_lane",)))).status is Status.BLOCKED
    )


def test_explicit_selection_without_integration_artifact_blocks() -> None:
    # Routed explicitly (no integration surface) with only a non-integration
    # artifact: the family must still require integration evidence.
    arts = [art("sc", Authority.PRODUCT, ArtifactKind.SCORECARD, {"verdict": "pass"})]
    assert only(validate(ctx_for(arts, ["sc"]))).status is Status.BLOCKED


def test_product_verdict_alongside_lane_passes() -> None:
    # A cross-family pack: the product verdict legitimately decides; the optional
    # lane is declared optional. The product verdict must not read as an unbounded
    # judge/RAG integration.
    arts = [
        art(
            "v",
            Authority.PRODUCT,
            ArtifactKind.VERDICT,
            {"verdict": "pass", "decides_verdict": True},
        ),
        art("phoenix", content={"lane": "phoenix", "optional": True}),
    ]
    assert only(validate(ctx_for(arts, ["v", "phoenix"]))).status is Status.PASS


def test_rag_without_influence_declaration_blocks() -> None:
    arts = [art("rag", content={"rag": True})]  # no influences_verdict / declared_boundary
    assert only(validate(ctx_for(arts, ["rag"], surfaces=("rag",)))).status is Status.BLOCKED


def test_no_required_evidence_blocks() -> None:
    arts = [art("phoenix", content={"lane": "phoenix", "optional": True})]
    assert only(validate(ctx_for(arts, []))).status is Status.BLOCKED


# --- end to end -------------------------------------------------------------


def test_runner_fails_on_optional_lane_as_required() -> None:
    arts = [art("lane", content={"lane": "ragas", "optional": True, "treated_as_required": True})]
    claim = Claim(
        id="c1",
        text="optional lane is required",
        expected_families=[FamilyId.INTEGRATION_BOUNDARY],
        required_artifacts=["lane"],
    )
    pack = EvidencePack(
        checkpoint="cp",
        source_boundary={"external_contracts": ["lane"]},
        artifacts=arts,
        claims=[claim],
    )
    result = run_validation(pack)
    assert result.status is Status.FAIL
    assert result.families_run == ["integration_boundary"]
