from scripts.benchmark_subject_actions import validate_manifest


def test_subject_action_requires_region_and_accepted_asset():
    payload = {
        "template": "animal_diorama",
        "experience_kind": "interactive_subject",
        "subject_regions": [{"region_id": "head", "x": 0.2, "y": 0.2, "width": 0.3, "height": 0.3}],
        "actions": [{"action_id": "pet", "target_region_id": "head", "status": "experimental", "cooldown_ms": 1200}],
    }
    report = validate_manifest(payload)
    assert report["accepted_action_count"] == 0
    assert report["checks"][0]["valid"] is False
    assert "asset_not_accepted" in report["checks"][0]["reasons"]
    assert report["non_target_click"] == "no-op"


def test_subject_action_rejects_invalid_target_box():
    payload = {
        "subject_regions": [{"region_id": "head", "x": 0.9, "y": 0.2, "width": 0.3, "height": 0.3}],
        "actions": [{"action_id": "pet", "target_region_id": "head", "status": "available", "cooldown_ms": 1200}],
    }
    report = validate_manifest(payload)
    assert "missing_or_invalid_target_region" in report["checks"][0]["reasons"]
