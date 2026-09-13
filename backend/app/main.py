from __future__ import annotations

import hashlib
import secrets
import shutil
import uuid
from io import BytesIO
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Cookie, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from app.config import settings
from app.models import Job, JobState, SceneManifest
from app.services.geometry import generate_scene
from app.services.photo_plan import analyze_photo

app = FastAPI(title="走进照片 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
settings.ensure_dirs()
analyses: dict[str, object] = {}
jobs: dict[str, Job] = {}
sessions: set[str] = set()


class AccessRequest(BaseModel):
    code: str


class AccessResponse(BaseModel):
    ok: bool


def _require_session(session: str | None) -> None:
    if not session or session not in sessions:
        raise HTTPException(status_code=401, detail="需要有效邀请码")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "mock_mode": settings.mock_mode, "mock_geometry": settings.mock_geometry}


@app.post("/api/access", response_model=AccessResponse)
def access(payload: AccessRequest) -> AccessResponse:
    if not secrets.compare_digest(payload.code, settings.invite_code):
        raise HTTPException(status_code=403, detail="邀请码不正确")
    token = secrets.token_urlsafe(24)
    sessions.add(token)
    response = AccessResponse(ok=True)
    # Cookie is attached manually so this endpoint stays easy to test with curl.
    from fastapi.responses import JSONResponse
    result = JSONResponse(response.model_dump())
    result.set_cookie("walk_session", token, httponly=True, samesite="lax", max_age=86400)
    return result


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), walk_session: str | None = Cookie(default=None)):
    _require_session(walk_session)
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=415, detail="只支持 JPEG、PNG、WebP")
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="图片不能超过10MB")
    upload_id = uuid.uuid4().hex
    safe_path = settings.uploads_dir / f"{upload_id}{suffix}"
    # Decode and re-encode so corrupt files are rejected and EXIF metadata is not
    # carried into the model request or generated scene.
    try:
        with Image.open(BytesIO(content)) as image:
            image.load()
            image_format = image.format or suffix.removeprefix(".").upper()
            normalized = image.convert("RGBA" if "A" in image.getbands() and image_format in {"PNG", "WEBP"} else "RGB")
            save_kwargs = {"exif": b""}
            if image_format in {"JPEG", "WEBP"}:
                save_kwargs["quality"] = 92
            normalized.save(safe_path, format=image_format, **save_kwargs)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="图片文件损坏或无法读取") from exc
    try:
        plan = await analyze_photo(safe_path, settings)
        analyses[plan.analysis_id] = {"plan": plan, "path": safe_path, "filename": file.filename}
        return plan
    except Exception as exc:
        safe_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=f"照片分析失败：{type(exc).__name__}") from exc


class CreateJobRequest(BaseModel):
    analysis_id: str


@app.post("/api/jobs", response_model=Job)
def create_job(payload: CreateJobRequest, walk_session: str | None = Cookie(default=None)) -> Job:
    _require_session(walk_session)
    record = analyses.get(payload.analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="分析结果不存在或已过期")
    existing = next((job for job in jobs.values() if job.analysis_id == payload.analysis_id), None)
    if existing:
        return existing
    if len([j for j in jobs.values() if j.state in {JobState.queued, JobState.generating}]) >= 1:
        raise HTTPException(status_code=429, detail="当前已有生成任务，请稍后再试")
    plan = record["plan"]
    if plan.suitability.value == "reject":
        raise HTTPException(status_code=422, detail="这张照片不适合当前体验")
    job_id = uuid.uuid4().hex
    job = Job(job_id=job_id, analysis_id=payload.analysis_id, filename=record["filename"], state=JobState.queued, message="已进入生成队列", created_at=datetime.now(timezone.utc))
    jobs[job_id] = job
    return _run_job(job, record)


def _run_job(job: Job, record: dict) -> Job:
    job.state = JobState.generating
    job.progress = 45
    job.message = "正在生成演示几何"
    scene_id = uuid.uuid4().hex
    scene_path = settings.scenes_dir / scene_id / "scene.glb"
    try:
        result = generate_scene(record["path"], scene_path, mock=settings.mock_geometry, settings=settings)
        job.state = JobState.validating
        job.progress = 85
        job.message = "正在检查场景"
        if result["coverage"] < 0.8:
            raise ValueError("有效几何覆盖率不足")
        job.state = JobState.ready
        job.progress = 100
        job.message = "场景已准备好"
        job.scene_id = scene_id
        job.expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.scene_ttl_hours)
        # Delete the original after the generation step; keep only the deliverable.
        Path(record["path"]).unlink(missing_ok=True)
    except Exception as exc:
        job.state = JobState.failed
        job.error = type(exc).__name__
        job.message = "生成失败，请更换照片或稍后重试"
    return job


@app.get("/api/jobs/{job_id}", response_model=Job)
def get_job(job_id: str, walk_session: str | None = Cookie(default=None)) -> Job:
    _require_session(walk_session)
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@app.get("/api/scenes/{scene_id}/manifest", response_model=SceneManifest)
def get_manifest(scene_id: str, walk_session: str | None = Cookie(default=None)) -> SceneManifest:
    _require_session(walk_session)
    job = next((j for j in jobs.values() if j.scene_id == scene_id), None)
    if not job or not job.expires_at or job.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="场景已过期")
    return SceneManifest(scene_id=scene_id, scene_url=f"/api/scenes/{scene_id}/scene.glb", download_url=f"/api/scenes/{scene_id}/scene.glb", movement_radius=0.55, generated_region_note="照片不可见区域由AI估计补全；当前演示使用占位几何。", expires_at=job.expires_at, mock=settings.mock_geometry)


@app.get("/api/scenes/{scene_id}/scene.glb")
def get_scene(scene_id: str, walk_session: str | None = Cookie(default=None)):
    _require_session(walk_session)
    path = settings.scenes_dir / scene_id / "scene.glb"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="场景不存在")
    return FileResponse(path, media_type="model/gltf-binary", filename="scene.glb")
