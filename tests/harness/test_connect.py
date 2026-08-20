"""`connect --live` connector-lane scaffold (EG-P2-1/2): fail-closed, idempotent, secret-safe."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from evalglass.harness import connect
from evalglass.harness.config import LaneConfig, RuntimeConfig


def _metric() -> dict[str, object]:
    return {
        "name": "field_presence",
        "evaluator_ref": "field_presence@1",
        "lens": "non_reference",
        "score_type": "continuous",
        "score_range": [0, 1],
    }


@pytest.mark.parametrize(
    ("platform", "lane"),
    [
        ("langfuse", "langfuse-trace"),
        ("phoenix", "phoenix-trace"),
        ("langsmith", "langsmith-trace"),
    ],
)
def test_scaffold_maps_platform_to_lane(platform: str, lane: str) -> None:
    cfg = connect.connector_lane_config(platform)
    assert cfg["name"] == lane
    assert cfg["enabled"] is True
    assert cfg["data_policy"] == "unknown"  # fail-closed egress by default
    # The lane mapping is a runnable LaneConfig (known name, valid shape).
    assert LaneConfig.from_mapping(cfg, 0).name == lane


def test_default_credentials_are_env_var_names_never_secrets() -> None:
    cfg = connect.connector_lane_config("langfuse")
    creds = cfg["options"]["credentials"]
    assert creds == {"public_key": "LANGFUSE_PUBLIC_KEY", "secret_key": "LANGFUSE_SECRET_KEY"}
    # every credential value is a bare ENV-VAR NAME (a reference), not a literal token
    assert all(
        v.replace("_", "").isalnum() and not v.startswith(("sk-", "pk-")) for v in creds.values()
    )


def test_unknown_platform_fails_closed_listing_valid() -> None:
    with pytest.raises(connect.ConnectError) as ei:
        connect.connector_lane_config("bogus")
    msg = str(ei.value)
    assert "langfuse" in msg
    assert "phoenix" in msg
    assert "langsmith" in msg


def test_literal_secret_credential_is_rejected_and_not_echoed() -> None:
    # A literal (not an env-var NAME) — hyphens make it invalid, so the boundary rejects it. We use
    # a non-key-shaped string deliberately: a real secret must never appear in the codebase.
    literal_value = "inline-literal-value-not-an-env-name"
    with pytest.raises(connect.ConnectError) as ei:
        connect.connector_lane_config("langfuse", credentials={"public_key": literal_value})
    assert literal_value not in str(ei.value)  # the rejected literal must never leak into the error


def test_scaffold_config_round_trips_through_runtime_config(tmp_path: Path) -> None:
    lane = connect.connector_lane_config("langfuse", endpoint="https://lf.example")
    cfg = RuntimeConfig.from_mapping({"metrics": [_metric()], "lanes": [lane]})
    assert cfg.lanes[0].name == "langfuse-trace"
    assert cfg.lanes[0].enabled is True


def test_apply_connect_creates_lane_block(tmp_path: Path) -> None:
    path = tmp_path / "evalglass.yaml"
    path.write_text(yaml.safe_dump({"metrics": [_metric()]}), encoding="utf-8")
    connect.apply_connect(path, "langfuse", endpoint="https://lf.example")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "metrics" in doc  # host key preserved
    assert [ln["name"] for ln in doc["lanes"]] == ["langfuse-trace"]
    assert doc["lanes"][0]["data_policy"] == "unknown"


def test_apply_connect_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "evalglass.yaml"
    path.write_text(yaml.safe_dump({"metrics": [_metric()], "datasets": [{"path": "d.jsonl"}]}))
    connect.apply_connect(path, "langfuse", endpoint="https://a.example")
    connect.apply_connect(path, "langfuse", endpoint="https://b.example")  # re-run updates
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    langfuse_lanes = [ln for ln in doc["lanes"] if ln["name"] == "langfuse-trace"]
    assert len(langfuse_lanes) == 1  # never duplicated
    assert langfuse_lanes[0]["options"]["endpoint"] == "https://b.example"  # updated in place
    assert doc["datasets"] == [{"path": "d.jsonl"}]  # unrelated host keys intact


def test_apply_connect_preserves_other_lanes(tmp_path: Path) -> None:
    path = tmp_path / "evalglass.yaml"
    existing = {"metrics": [_metric()], "lanes": [{"name": "phoenix-trace", "enabled": True}]}
    path.write_text(yaml.safe_dump(existing))
    connect.apply_connect(path, "langfuse", endpoint="https://lf.example")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert {ln["name"] for ln in doc["lanes"]} == {"phoenix-trace", "langfuse-trace"}
