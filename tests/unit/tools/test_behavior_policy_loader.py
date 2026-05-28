from pathlib import Path

from brain_researcher.services.agent.resources.behavior_policies import (
    load_behavior_policies,
)


def test_load_behavior_policies_scans_directory(tmp_path: Path):
    policy1 = tmp_path / "p1.yaml"
    policy2 = tmp_path / "p2.json"
    policy1.write_text(
        "policy_id: custom1\nrt_min_sec: 0.2\nrt_max_sec: 2.5\n", encoding="utf-8"
    )
    policy2.write_text(
        '{"policy_id": "custom2", "accuracy_min": 0.7, "miss_rate_max": 0.1}', encoding="utf-8"
    )

    policies = load_behavior_policies([str(tmp_path)])
    ids = {p["policy_id"] for p in policies}
    assert ids == {"custom1", "custom2"}
    # Ensure fields parsed
    p1 = next(p for p in policies if p["policy_id"] == "custom1")
    assert p1["rt_min_sec"] == 0.2
    p2 = next(p for p in policies if p["policy_id"] == "custom2")
    assert p2["miss_rate_max"] == 0.1
