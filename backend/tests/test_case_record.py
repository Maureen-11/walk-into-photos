from pathlib import Path

import pytest

from app.services.case_record import CaseRecord, read_case, write_case


def test_write_and_read_case_creates_independent_files(tmp_path: Path):
    record = CaseRecord(
        case_id="cat-response-001",
        result="failure",
        title="笼中双猫摸头试验",
        expected="只让目标猫头回应，背景保持稳定",
        actual="定位不稳定，保留原图并记录失败",
        model_versions={"planner": "local-test"},
        hardware={"gpu": "RTX 4050 Laptop GPU", "vram_mib": 6141},
        timings_ms={"total": 1234},
        evidence=["evidence/run-01.mp4"],
        reproduce_steps=["上传样片", "在右侧猫头区域拖动鼠标"],
    )

    case_dir = write_case(tmp_path, record)

    assert (case_dir / "case.json").is_file()
    assert (case_dir / "README.md").is_file()
    assert (case_dir / "evidence").is_dir()
    assert (case_dir / "input").is_dir()
    assert read_case(case_dir)["result"] == "failure"
    assert "笼中双猫" in (case_dir / "README.md").read_text(encoding="utf-8")


def test_sensitive_values_and_absolute_paths_are_redacted(tmp_path: Path):
    record = CaseRecord(
        case_id="offline-check-001",
        result="success",
        title="离线检查",
        expected="不联网",
        actual="通过",
        params={"token": "do-not-write", "resize": 768},
        notes="password=do-not-write C:\\Users\\Alice\\private.png",
        evidence=[r"C:\Users\Alice\screen.png"],
    )

    case_dir = write_case(tmp_path, record)
    json_text = (case_dir / "case.json").read_text(encoding="utf-8")
    readme_text = (case_dir / "README.md").read_text(encoding="utf-8")

    assert "do-not-write" not in json_text
    assert "do-not-write" not in readme_text
    assert "<local>/screen.png" in json_text
    assert "C:\\Users\\Alice" not in readme_text


def test_case_ids_are_validated_and_existing_case_is_preserved(tmp_path: Path):
    with pytest.raises(ValueError):
        write_case(tmp_path, CaseRecord("../bad", "failure", "标题", "预期", "实际"))

    record = CaseRecord("same-case-001", "success", "标题", "预期", "实际")
    write_case(tmp_path, record)
    with pytest.raises(FileExistsError):
        write_case(tmp_path, record)
