from datetime import datetime, timezone

from app import main
from app.models import GenerationMode, Job, JobState


def _job(state: JobState) -> Job:
    now = datetime.now(timezone.utc)
    return Job(
        job_id="recovery-job-001",
        analysis_id="analysis-001",
        filename="sample.jpg",
        generation_mode=GenerationMode.quick,
        selected_template="landscape_journey",
        state=state,
        created_at=now,
        updated_at=now,
    )


def test_recovery_marks_inflight_job_interrupted(monkeypatch):
    stored: dict[str, str] = {}
    original = _job(JobState.quick_generating)
    stored[original.job_id] = original.model_dump_json()

    class FakeStore:
        def list_jobs(self):
            return list(stored.values())

        def save_job(self, job_id: str, payload: str):
            stored[job_id] = payload

    monkeypatch.setattr(main, "store", FakeStore())
    main._recover_interrupted_jobs()

    recovered = Job.model_validate_json(stored[original.job_id])
    assert recovered.state is JobState.interrupted
    assert recovered.error == "PROCESS_RESTARTED"
    assert "重启" in recovered.message


def test_recovery_leaves_ready_job_unchanged(monkeypatch):
    stored: dict[str, str] = {}
    original = _job(JobState.quick_ready)
    stored[original.job_id] = original.model_dump_json()

    class FakeStore:
        def list_jobs(self):
            return list(stored.values())

        def save_job(self, job_id: str, payload: str):
            stored[job_id] = payload

    monkeypatch.setattr(main, "store", FakeStore())
    main._recover_interrupted_jobs()

    recovered = Job.model_validate_json(stored[original.job_id])
    assert recovered.state is JobState.quick_ready
    assert recovered.error is None
