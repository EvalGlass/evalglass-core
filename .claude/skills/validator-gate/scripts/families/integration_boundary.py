"""integration_boundary family (VG-P1-6).

Optional stays optional; vendored material is not original; judges/RAG declare
their influence; hidden inputs cannot back controlled claims. The family
consumes (never duplicates) Scan Gate mechanical evidence and reasons over
integration-artifact content. Conventions:

- a lane carries ``lane`` (name) and ``optional`` / ``required``;
  ``treated_as_required: true`` means an optional lane is being required;
- a judge/RAG artifact carries ``influences_verdict`` and ``declared_boundary``;
- vendored/copied material carries ``vendored``/``copied`` and
  ``treated_as_original``;
- ``hidden_input: true`` marks an undeclared input.

Outcomes:
- FAIL: an optional lane treated as required; judge/RAG influence without a
  declared boundary; vendored/copied material treated as original; a hidden
  input backing a controlled/reproducible claim.
- BLOCKED: no evidence; a lane with undeclared optionality; an integration claim
  with no integration artifact.
- PASS: a declared-optional lane not required; declared boundaries.
"""

from __future__ import annotations

from typing import Any

from scripts.contracts import Authority, FamilyFinding, FamilyId, Status
from scripts.families.base import FamilyContext, finding, probe

RISK_REF = "optional_lanes_deletion"

_CONTROLLED_SURFACES = {"reproducibility", "reproducible", "hermetic", "controlled"}
# Content keys that mark an artifact as integration evidence. Includes the
# standard vendoring shapes (a manifest's managed_root / all_under_managed_root,
# a lock's skill_vendored) so real vendoring evidence is recognized without a
# synthetic lane marker.
_INTEGRATION_MARKERS = (
    "lane",
    "vendored",
    "copied",
    "skill_vendored",
    "managed_root",
    "all_under_managed_root",
    "influences_verdict",
    "rag",
    "runtime_route",
    "hidden_input",
)
# Any of these being truthy means the artifact carries vendored/copied material.
_VENDORED_FLAGS = ("vendored", "copied", "skill_vendored")
# A vendored *runtime* (as opposed to a separately-declared copied file) asserts
# managed material that must be proven bounded by a manifest. ``copied`` is
# excluded: declaring copied/product separation needs no managed root.
_MANIFEST_REQUIRED_FLAGS = ("vendored", "skill_vendored")


def _block(ctx: FamilyContext, reason: str, remediation: str) -> list[FamilyFinding]:
    return [
        finding(
            ctx,
            FamilyId.INTEGRATION_BOUNDARY,
            Status.BLOCKED,
            reason=reason,
            remediation=remediation,
            risk_ref=RISK_REF,
        )
    ]


def _fail(
    ctx: FamilyContext, reason: str, remediation: str, evidence_refs: list[str]
) -> list[FamilyFinding]:
    return [
        finding(
            ctx,
            FamilyId.INTEGRATION_BOUNDARY,
            Status.FAIL,
            reason=reason,
            remediation=remediation,
            evidence_refs=evidence_refs,
            risk_ref=RISK_REF,
        )
    ]


def _is_integration(content: dict[str, Any] | None) -> bool:
    return any(probe(content, marker) is not None for marker in _INTEGRATION_MARKERS)


def _acts_as_product(content: dict[str, Any] | None) -> bool:
    return (
        probe(content, "acts_as") in {"product", "canonical"}
        or probe(content, "authoritative") is True
    )


def _valid_root(root: object) -> bool:
    """A managed root must be a concrete, non-escaping subtree.

    Rejects non-strings, blank/whitespace, whole-tree roots (a bare ``/``, ``.``
    or ``./``), and any empty/``.``/``..`` segment — none bound vendored material
    to a managed subtree, so trusting a summary flag against them would
    manufacture a PASS.
    """
    if not isinstance(root, str):
        return False
    if root != root.strip():
        return False  # exact evidence: surrounding whitespace is malformed
    base = root.rstrip("/")
    if not base or base == ".":
        return False
    return not any(seg in ("", ".", "..") for seg in base.split("/"))


def _classify_record(record: object, base: str) -> str:
    """Classify one manifest file record: under | leak | malformed.

    ``under`` is a file strictly beneath the managed root; ``leak`` is a usable
    path that resolves outside it (incl. ``..`` escapes); ``malformed`` is a
    record with no usable string path, or one equal to the root dir itself (a
    file record equal to the directory proves no file under the subtree).
    """
    path = record.get("path") if isinstance(record, dict) else record
    if not isinstance(path, str):
        return "malformed"
    if ".." in path.split("/"):
        # A lexical prefix check alone passes "<root>/../x", which escapes.
        return "leak"
    # Manifest paths are exact evidence: only a trailing slash is normalized (a
    # directory spelling), never surrounding whitespace, so a whitespace-prefixed
    # path falls through to "leak" rather than being trimmed into a PASS.
    candidate = path.rstrip("/")
    if not candidate or candidate == base:
        # Empty, or the managed root dir itself (with or without a trailing
        # slash) -> proves no file beneath the subtree.
        return "malformed"
    if candidate.startswith(base + "/"):
        return "under"
    return "leak"


# A boundedness claim is identified by managed-root markers only. A bare
# ``files`` array (e.g. on an unrelated review manifest) is not a vendoring
# boundary claim and must not drive this check.
_BOUNDEDNESS_MARKERS = ("managed_root", "all_under_managed_root")


def _boundedness(content: dict[str, Any] | None) -> str | None:
    """Classify a manifest's boundedness: bounded | unbounded | unproven | None.

    ``None`` means the artifact makes no boundedness claim at all. Once a
    managed-root marker (``managed_root`` / ``all_under_managed_root``) is present
    the artifact *does* make a claim, and — content being schema-open — a
    malformed or unprovable claim is ``unproven`` (fail closed), never ``None``.
    Concrete ``files`` records are the strongest proof and are always checked (a
    stale ``all_under_managed_root: true`` must not mask a leak); an explicit
    ``all_under_managed_root: false`` is the producer asserting a leak and wins
    regardless of records. A proven leak outranks a malformed record regardless
    of order.
    """
    managed_root = probe(content, "managed_root")
    explicit = probe(content, "all_under_managed_root")
    files = probe(content, "files")
    if not any(probe(content, m) is not None for m in _BOUNDEDNESS_MARKERS):
        return None
    # An explicit ``false`` summary asserts a leak; honor it even when records or
    # the root are missing/malformed.
    if explicit is False:
        return "unbounded"
    # Without a concrete, non-escaping managed root the claim cannot be
    # positively proven (malformed/blank/`..` root) -> fail closed.
    if not _valid_root(managed_root):
        return "unproven"
    # Records, once present in any shape, are the strongest proof and must not be
    # masked by a summary flag. A malformed or empty collection cannot prove
    # boundedness -> unproven; any record escaping the root is a proven leak.
    if files is not None:
        if not isinstance(files, list) or not files:
            return "unproven"
        base = managed_root.rstrip("/")
        states = [_classify_record(r, base) for r in files]
        if "leak" in states:
            return "unbounded"
        if "malformed" in states:
            return "unproven"
        return "bounded"
    if explicit is True:
        return "bounded"
    return "unproven"


def validate(ctx: FamilyContext) -> list[FamilyFinding]:
    required = list({a.id: a for a in ctx.index.required_artifacts(ctx.claim.id)}.values())
    if not required:
        return _block(
            ctx,
            "integration_boundary claim has no required artifacts to inspect",
            "Declare the lane/judge/vendoring/route artifacts this claim depends on.",
        )
    surfaces = {str(s).strip().lower() for s in ctx.claim.risk_surfaces}

    # This family only validates integration claims, so it always needs an
    # integration artifact — regardless of how it was routed (explicit family
    # selection has no risk_surfaces). Absence is a fail-closed BLOCKED.
    if not any(_is_integration(a.content) for a in required):
        return _block(
            ctx,
            "integration_boundary claim has no integration artifact to inspect",
            "Include the lane/judge/vendoring/route artifact the claim covers.",
        )

    # Boundedness of any managed material, and the set of judge/RAG signals, are
    # needed by both the FAIL and BLOCKED checks below.
    boundedness = {a.id: _boundedness(a.content) for a in required}
    # A judge/RAG integration signal that can change status needs a declared
    # boundary. The product verdict legitimately decides (authority_verdict owns
    # that); only non-product integration artifacts are checked here.
    judge_rag = [
        a
        for a in required
        if a.authority is not Authority.PRODUCT
        and (
            probe(a.content, "rag") is not None
            or probe(a.content, "judge") is not None
            or probe(a.content, "influences_verdict") is not None
        )
    ]

    # ---- FAIL checks (proven violations) run before the fail-closed BLOCKED
    # checks, so a real violation surfaces as FAIL even when an adjacent artifact
    # is unproven. The composer can only enforce FAIL > BLOCKED across families
    # if this family emits the FAIL it can prove. ----

    # Vendored/copied material must not be treated as original product evidence.
    vendored = sorted(
        a.id
        for a in required
        if any(probe(a.content, flag) is True for flag in _VENDORED_FLAGS)
        and (probe(a.content, "treated_as_original") is True or _acts_as_product(a.content))
    )
    if vendored:
        return _fail(
            ctx,
            f"vendored/copied material {vendored} is treated as original product evidence",
            "Keep vendored/copied material distinct from original product evidence.",
            vendored,
        )

    # Managed/vendored material that leaks outside its declared managed root.
    unbounded_material = sorted(aid for aid, state in boundedness.items() if state == "unbounded")
    if unbounded_material:
        return _fail(
            ctx,
            f"managed/vendored material {unbounded_material} is not bounded to the managed root "
            "(a managed file lies outside it)",
            "Keep all managed/vendored files under the declared managed root.",
            unbounded_material,
        )

    # A judge/RAG signal that can change status without a declared boundary.
    unbounded_influence = sorted(
        a.id
        for a in judge_rag
        if probe(a.content, "influences_verdict") is True
        and not probe(a.content, "declared_boundary")
    )
    if unbounded_influence:
        return _fail(
            ctx,
            f"integration artifact(s) {unbounded_influence} can influence the verdict "
            "without a declared boundary",
            "Declare the judge/RAG boundary, or stop letting the integration affect the verdict.",
            unbounded_influence,
        )

    # An optional lane treated as required is a hidden requirement.
    required_optional = sorted(
        a.id
        for a in required
        if probe(a.content, "optional") is True and probe(a.content, "treated_as_required") is True
    )
    if required_optional:
        return _fail(
            ctx,
            f"optional lane(s) {required_optional} are treated as required "
            "without being declared so",
            "Either declare the lane required in the checkpoint, or keep it optional.",
            required_optional,
        )

    # A hidden input cannot support a controlled/reproducible claim.
    if surfaces & _CONTROLLED_SURFACES:
        hidden = sorted(a.id for a in required if probe(a.content, "hidden_input") is True)
        if hidden:
            return _fail(
                ctx,
                f"controlled/reproducible claim relies on hidden input(s) {hidden}",
                "Declare every input; a hidden input cannot back a hermetic/reproducible claim.",
                hidden,
            )

    # ---- BLOCKED checks (fail-closed on unproven / undeclared evidence). ----

    # The boundary is proven if any artifact carries bounded proof. A plan or
    # install summary may legitimately carry ``managed_root`` without files; it
    # only blocks when *nothing* in the pack proves the boundary, so a real
    # manifest's proof is not masked by an adjacent unproven summary.
    bounded_proof = any(state == "bounded" for state in boundedness.values())

    # A managed-root claim with no boundedness proof anywhere in the pack.
    unproven = sorted(aid for aid, state in boundedness.items() if state == "unproven")
    if unproven and not bounded_proof:
        return _block(
            ctx,
            f"manifest(s) {unproven} declare a managed_root but no artifact provides boundedness "
            "proof (no all_under_managed_root flag and no files records)",
            "Include the manifest's file records (or an all_under_managed_root flag).",
        )

    # A vendored *runtime* (vendored/skill_vendored) needs a bounded manifest
    # proof somewhere in the evidence; otherwise the "bounded" claim is
    # unverifiable -> fail closed. Copied/product separation is excluded.
    vendored_runtime = any(
        any(probe(a.content, flag) is True for flag in _MANIFEST_REQUIRED_FLAGS) for a in required
    )
    if vendored_runtime and not bounded_proof:
        return _block(
            ctx,
            "a vendored runtime is asserted but no bounded-manifest proof is present",
            "Include the vendor manifest (managed_root + files, or all_under_managed_root) "
            "proving the vendored runtime is bounded.",
        )

    # A lane must declare its optionality.
    undeclared = sorted(
        a.id
        for a in required
        if probe(a.content, "lane") is not None
        and probe(a.content, "optional") is None
        and probe(a.content, "required") is None
    )
    if undeclared:
        return _block(
            ctx,
            f"lane(s) {undeclared} do not declare whether they are optional or required",
            "Declare each lane's optionality so optional integrations stay optional.",
        )

    # A judge/RAG artifact must declare whether it influences the verdict (and,
    # if it does, its boundary). An undeclared judge/RAG signal is unverifiable.
    undeclared_influence = sorted(
        a.id
        for a in judge_rag
        if probe(a.content, "influences_verdict") is None
        and not probe(a.content, "declared_boundary")
    )
    if undeclared_influence:
        return _block(
            ctx,
            f"judge/RAG artifact(s) {undeclared_influence} do not declare their verdict influence",
            "Declare influences_verdict (and a boundary if it can influence the verdict).",
        )

    return [
        finding(
            ctx,
            FamilyId.INTEGRATION_BOUNDARY,
            Status.PASS,
            reason="integrations stay bounded: optional lanes are not required, "
            "influence is declared",
            evidence_refs=sorted(a.id for a in required),
        )
    ]
