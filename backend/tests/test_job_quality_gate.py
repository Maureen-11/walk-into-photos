from datetime import datetime, timezone

from app import main
from app.models import GenerationMode, Job, JobState, PhotoCategory, SceneTemplate
from app.services.photo_plan import build_plan


def _job(mode: GenerationMode) -> Job:
    now = datetime.now(timezone.utc)
    return Job(
        job_id="quality-job-001",
        analysis_id="analysis-001",
        filename="sample.jpg",
        generation_mode=mode,
        selected_template=SceneTemplate.generic_layers,
        state=JobState.queued,
        created_at=now,
        updated_at=now,
    )


def test_old_job_without_quality_status_defaults_to_unverified():
    job = _job(GenerationMode.quick)
    payload = job.model_dump()
    payload.pop("quality_status")

    restored = Job.model_validate(payload)

    assert restored.quality_status == "unverified"
    assert restored.validation_status == "not_run"


def test_quick_machine_failure_cannot_be_promoted(monkeypatch):
    job = _job(GenerationMode.quick)
    monkeypatch.setattr(main, "_load_job", lambda job_id: job)
    monkeypatch.setattr(main, "_save_job", lambda next_job: None)
    monkeypatch.setattr(main, "_generate_version", lambda *args, **kwargs: "quick-failed")
    monkeypatch.setattr(main, "_scene_quality_status", lambda scene_id: "failed")

    main._run_job(job.job_id, {"path": "unused", "filename": job.filename}, build_plan(PhotoCategory.other, "sample"))

    assert job.state is JobState.failed
    assert job.quick_scene_id == "quick-failed"
    assert job.scene_id is None
    assert job.quality_status == "failed"
    assert job.validation_status == "failed"
    assert job.error == "QUICK_MACHINE_QUALITY_FAILED"


def test_full_machine_failure_keeps_quick_scene_but_not_full_candidate(monkeypatch):
    job = _job(GenerationMode.progressive)
    monkeypatch.setattr(main, "_load_job", lambda job_id: job)
    monkeypatch.setattr(main, "_save_job", lambda next_job: None)
    monkeypatch.setattr(main, "_generate_version", lambda _job, _record, _plan, version: f"{version}-id")
    monkeypatch.setattr(
        main,
        "_scene_quality_status",
        lambda scene_id: "needs_visual_review" if scene_id == "quick-id" else "failed",
    )

    main._run_job(job.job_id, {"path": "unused", "filename": job.filename}, build_plan(PhotoCategory.other, "sample"))

    assert job.state is JobState.quick_ready
    assert job.quick_scene_id == "quick-id"
    assert job.full_scene_id == "full-id"
    assert job.scene_id == "quick-id"
    assert job.error == "FULL_MACHINE_QUALITY_FAILED"
    assert job.quality_status == "failed"
    assert job.validation_status == "failed"


def test_full_candidate_without_safe_comparison_keeps_quick_scene(monkeypatch):
    job = _job(GenerationMode.progressive)
    monkeypatch.setattr(main, "_load_job", lambda job_id: job)
    monkeypatch.setattr(main, "_save_job", lambda next_job: None)
    monkeypatch.setattr(main, "_generate_version", lambda _job, _record, _plan, version: f"{version}-id")
    monkeypatch.setattr(main, "_scene_quality_status", lambda scene_id: "needs_visual_review")
    monkeypatch.setattr(
        main,
        "_compare_upgrade_versions",
        lambda quick_id, full_id: {
            "measurable_upgrade_candidate": False,
            "machine_status": "needs_visual_review",
            "warnings": ["缺少同路线验收证据"],
        },
    )
    monkeypatch.setattr(main, "_record_upgrade_comparison", lambda scene_id, comparison: None)

    main._run_job(job.job_id, {"path": "unused", "filename": job.filename}, build_plan(PhotoCategory.other, "sample"))

    assert job.state is JobState.quick_ready
    assert job.quick_scene_id == "quick-id"
    assert job.full_scene_id == "full-id"
    assert job.scene_id == "quick-id"
    assert job.error == "FULL_UPGRADE_NOT_PROMOTED"
    assert job.quality_status == "needs_visual_review"
    assert job.validation_status == "needs_review"


def test_cancellation_is_terminal_and_preserves_completed_quick_scene(monkeypatch):
    job = _job(GenerationMode.progressive)
    job.cancel_requested = True
    job.quick_scene_id = "quick-id"
    job.scene_id = "quick-id"
    monkeypatch.setattr(main, "_save_job", lambda next_job: None)

    assert main._cancel_job_if_requested(job, "full-id") is True

    assert job.state is JobState.cancelled
    assert job.scene_id == "quick-id"
    assert job.quick_scene_id == "quick-id"
    assert job.error == "CANCELLED"


def test_cancel_endpoint_marks_inflight_job_without_claiming_immediate_model_stop(monkeypatch):
    job = _job(GenerationMode.progressive)
    job.state = JobState.full_generating
    monkeypatch.setattr(main, "_load_job", lambda job_id: job)
    monkeypatch.setattr(main, "_save_job", lambda next_job: None)

    result = main.cancel_job(job.job_id)

    assert result is job
    assert job.cancel_requested is True
    assert job.state is JobState.full_generating
    assert "GPU 阶段结束" in job.message
