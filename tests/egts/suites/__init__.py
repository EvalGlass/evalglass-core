"""EGTS-M0 proof suites.

``M0_SCENARIO_IDS`` is the canonical set of EGTS-M0 scenario identifiers actually
exercised by ``egts test-core`` (the suites in this package). The coverage
registry may only mark an obligation ``covered`` with ids drawn from this set —
a meta-test enforces it — so a row can never claim proof that the EGTS suite does
not actually run.
"""

from __future__ import annotations

M0_SCENARIO_IDS: frozenset[str] = frozenset(
    {
        # tests/egts/suites/test_m0_core_proof.py
        "m0.proof.informational",
        "m0.proof.pass",
        "m0.proof.fail",
        "m0.proof.blocked_on_policy",
        "m0.proof.score_state_blocks_on_incomplete",
        "m0.proof.runrecord_round_trips",
        "m0.proof.comparability",
        "m0.proof.checker_negative_controls",
        # tests/egts/suites/test_m0_meta.py
        "m0.meta.core_is_effect_free",
        "m0.meta.blocked_zero_rejected",
        "m0.meta.mutated_verdict_rejected",
        "m0.meta.coverage_complete",
    }
)

#: The canonical set of EGTS-M5C (v2 alignment) scenario identifiers actually exercised by the
#: ``test_m5c_*_proof.py`` suites. The ``eg_m5c.yaml`` coverage registry may only mark an obligation
#: ``covered`` with ids drawn from this set — a meta-test (``test_v2_coverage_registry``) enforces
#: it — so a typo'd or stale ``m5c.*`` id can never satisfy the namespace check while naming a
#: scenario no suite runs. Mirrors the M0_SCENARIO_IDS guard.
M5C_SCENARIO_IDS: frozenset[str] = frozenset(
    {
        # test_m5c_seam_proof.py (EG-M5C-1)
        "m5c.runner_attach_seam",
        # test_m5c_dashboard_proof.py (EG-M5C-2)
        "m5c.dashboard.capture_export",
        "m5c.dashboard.egress_before_effects",
        "m5c.dashboard.deletion_invariant",
        # test_m5c_optimizer_proof.py (EG-M5C-3)
        "m5c.optimizer.write_only_handoff",
        "m5c.optimizer.no_write_back",
        "m5c.optimizer.no_recompute",
        # test_m5c_annotation_proof.py (EG-M5C-4)
        "m5c.annotation.no_record_no_authority",
        "m5c.annotation.typed_validation_record",
        "m5c.annotation.no_self_approval",
        # test_m5c_synthetic_proof.py (EG-M5C-5)
        "m5c.synthetic.forced_proposed",
        "m5c.synthetic.bypass_cannot_gate",
        "m5c.synthetic.host_validated_specificity",
        # test_m5c_connector_proof.py (EG-M5C-6)
        "m5c.trace.langfuse_normalization",
        "m5c.trace.phoenix_normalization",
        "m5c.trace.langsmith_normalization",
        # test_m5c_metrics_explorer_proof.py (EG-M5C-8)
        "m5c.metrics_explorer.typed_only",
        "m5c.metrics_explorer.group_by_identity",
        "m5c.metrics_explorer.old_artifact_refuses_guess",
    }
)
