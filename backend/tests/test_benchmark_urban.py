from pathlib import Path

import cv2
import numpy as np

from scripts.benchmark_urban import analyze


def _write_sample(path: Path) -> None:
    image = np.full((180, 280, 3), 245, dtype=np.uint8)
    cv2.line(image, (25, 20), (25, 165), (20, 20, 20), 4)
    cv2.line(image, (255, 20), (255, 165), (20, 20, 20), 4)
    cv2.line(image, (25, 130), (255, 130), (30, 30, 30), 4)
    encoded = cv2.imencode(".jpg", image)[1]
    encoded.tofile(str(path))


def test_urban_report_is_conservative_and_writes_overlay(tmp_path: Path):
    image = tmp_path / "sample.jpg"
    output = tmp_path / "evidence"
    _write_sample(image)

    report = analyze(image, output, "facade")

    assert report["kind"] == "facade"
    assert report["machine_status"] == "needs_visual_review"
    assert report["limitations"]
    assert (output / report["overlay"]).is_file()


def test_urban_report_rejects_unknown_route(tmp_path: Path):
    image = tmp_path / "sample.jpg"
    _write_sample(image)

    try:
        analyze(image, tmp_path / "evidence", "terrain")
    except ValueError as exc:
        assert "street 或 facade" in str(exc)
    else:
        raise AssertionError("unknown urban route should be rejected")
