from __future__ import annotations

import asyncio
import shutil
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from threading import Lock

from fastapi import Cookie, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from app.config import settings
from app.models import CameraSpec, GenerationMode, Job, JobState, PhotoPlan, SceneManifest, SceneTemplate
from app.services.geometry import generate_scene
from app.services.photo_plan import analyze_photo
from app.services.context_shell import add_context_shell
from app.services.scene_quality import inspect_scene
from app.services.templates import ENGINE_BY_TEMPLATE, movement_profile
from app.store import StateStore


app = FastAPI(title="走进照片 API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allow_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
settings.ensure_dirs()
store = StateStore(settings.database_path)
gpu_queue = ThreadPoolExecutor(max_workers=1, thread_name_prefix="walk-gpu")
job_creation_lock = Lock()

_OFFLINE_VIEWER_HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>走进照片 · 离线场景</title>
<style>html,body{margin:0;height:100%;background:#101022;color:#eee;font:14px system-ui,sans-serif}#hud{position:fixed;z-index:2;left:14px;top:14px;padding:10px 12px;border-radius:10px;background:#111126dd;max-width:380px}#view{width:100%;height:100%;display:block;cursor:grab;touch-action:none}</style>
<script type="importmap">{"imports":{"three":"./three.module.js"}}</script></head>
<body><div id="hud">正在加载离线场景…<br><small>拖动环顾 · WASD移动 · R回到起点</small></div><canvas id="view"></canvas>
<script type="module">
import * as THREE from './three.module.js';
import { GLTFLoader } from './GLTFLoader.js';
const canvas=document.querySelector('#view'),hud=document.querySelector('#hud');
const renderer=new THREE.WebGLRenderer({canvas,antialias:true}); renderer.setPixelRatio(Math.min(devicePixelRatio,2));
const scene=new THREE.Scene(); scene.background=new THREE.Color('#101022');
scene.add(new THREE.HemisphereLight('#ffffff','#202040',1.8)); const key=new THREE.DirectionalLight('#ffffff',1.4); key.position.set(4,8,4); scene.add(key);
const camera=new THREE.PerspectiveCamera(68,1,.01,200); let start=[0,1.5,2]; let yaw=0,pitch=0; const keys=new Set(); let dragging=false,last=[0,0];
let movement=null,flying=false;window.addEventListener('keydown',e=>{const key=e.key.toLowerCase();keys.add(key);if(key==='f'&&movement?.allow_flight)flying=!flying;if(key==='r'){camera.position.set(...start);yaw=0;pitch=0;flying=false}});window.addEventListener('keyup',e=>keys.delete(e.key.toLowerCase()));
canvas.addEventListener('pointerdown',e=>{dragging=true;last=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId)});canvas.addEventListener('pointerup',()=>dragging=false);canvas.addEventListener('pointermove',e=>{if(!dragging)return;yaw-=(e.clientX-last[0])*.005;pitch=Math.max(-1.35,Math.min(1.35,pitch-(e.clientY-last[1])*.005));last=[e.clientX,e.clientY]});
function resize(){const w=innerWidth,h=innerHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix()}addEventListener('resize',resize);resize();
fetch('./manifest.json').then(r=>r.json()).then(m=>{movement=m.movement;start=m.movement.start;camera.position.set(...start);if(m.camera){camera.fov=m.camera.fov_y||camera.fov;camera.near=m.camera.near||camera.near;camera.far=m.camera.far||camera.far;camera.updateProjectionMatrix()}hud.innerHTML=`<b>${m.template}</b> · ${m.version}<br><small>拖动环顾 · WASD移动 · R回到起点${m.movement.allow_flight?' · F飞行 · 空格上升 · C下降':''}</small>`}).catch(()=>{});
new GLTFLoader().load('./scene.glb',g=>{scene.add(g.scene);hud.innerHTML+='';},undefined,e=>{hud.textContent='离线场景加载失败：'+e.message});
const clock=new THREE.Clock();function loop(){requestAnimationFrame(loop);const d=Math.min(clock.getDelta(),.05);const f=Number(keys.has('w')||keys.has('arrowup'))-Number(keys.has('s')||keys.has('arrowdown'));const s=Number(keys.has('d')||keys.has('arrowright'))-Number(keys.has('a')||keys.has('arrowleft'));const speed=(flying&&movement?.allow_flight?movement.fly_speed:movement?.walk_speed||1.8)*d;camera.position.x+=Math.sin(yaw)*f*speed+Math.cos(yaw)*s*speed;camera.position.z+=-Math.cos(yaw)*f*speed+Math.sin(yaw)*s*speed;if(flying&&movement?.allow_flight){camera.position.y+=(Number(keys.has(' '))-Number(keys.has('c')))*speed}if(movement?.bounds){for(const axis of ['x','y','z']){const bounds=movement.bounds[axis];if(bounds)camera.position[axis]=Math.max(bounds[0],Math.min(bounds[1],camera.position[axis]))}}camera.rotation.set(pitch,yaw,0,'YXZ');renderer.render(scene,camera)}loop();
</script></body></html>"""


class AccessRequest(BaseModel):
    code: str = ""


class AccessResponse(BaseModel):
    ok: bool


class CreateJobRequest(BaseModel):
    analysis_id: str
    selected_template: SceneTemplate | None = None
    generation_mode: GenerationMode = GenerationMode.progressive


def _require_session(session: str | None) -> None:
    # Local demo mode is intentionally open. Keep the call sites and cookie
    # parameters for backwards compatibility with older clients, but do not
    # require or retain an invite/session credential.
    return None


def _load_job(job_id: str) -> Job | None:
    payload = store.get_job(job_id)
    return Job.model_validate_json(payload) if payload else None


def _save_job(job: Job) -> None:
    job.updated_at = datetime.now(timezone.utc)
    store.save_job(job.job_id, job.model_dump_json())


def _recover_interrupted_jobs() -> None:
    """Mark in-flight work as interrupted after a process restart.

    We do not silently re-run GPU work or claim resumability at an arbitrary
    model checkpoint. A later retry flow can deliberately create a new run
    while preserving this record.
    """

    for payload in store.list_jobs():
        job = Job.model_validate_json(payload)
        if job.state in {JobState.queued, JobState.quick_generating, JobState.full_generating}:
            job.state = JobState.interrupted
            job.error = "PROCESS_RESTARTED"
            job.message = "进程重启，任务已中断；快速结果若已存在仍可使用"
            _save_job(job)


_recover_interrupted_jobs()


def _active_jobs() -> list[Job]:
    active = []
    for payload in store.list_jobs():
        job = Job.model_validate_json(payload)
        if job.state in {JobState.queued, JobState.quick_generating, JobState.full_generating}:
            active.append(job)
    return active


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "mock_mode": settings.mock_mode,
        "mock_geometry": settings.mock_geometry,
        "local_planner": settings.local_planner_model if settings.local_planner_enabled else "disabled",
        "local_files_only": settings.local_files_only,
        "queue_active": len(_active_jobs()),
    }


@app.post("/api/access", response_model=AccessResponse)
def access(payload: AccessRequest | None = None):
    """Compatibility endpoint retained for older local clients.

    Access is open in the local demo; the submitted code is ignored and is
    never stored or echoed.
    """
    return AccessResponse(ok=True)


@app.post("/api/analyze", response_model=PhotoPlan)
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
    try:
        with Image.open(BytesIO(content)) as image:
            image.load()
            source_format = image.format or suffix.removeprefix(".").upper()
            normalized = image.convert("RGBA" if "A" in image.getbands() and source_format in {"PNG", "WEBP"} else "RGB")
            save_kwargs = {"exif": b""}
            if source_format in {"JPEG", "WEBP"}:
                save_kwargs["quality"] = 92
            normalized.save(safe_path, format=source_format, **save_kwargs)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="图片文件损坏或无法读取") from exc
    try:
        loop = asyncio.get_running_loop()
        # Analysis is also a model task; keep it on the same one-worker GPU
        # queue as generation so two requests cannot load models concurrently.
        plan = await loop.run_in_executor(gpu_queue, analyze_photo, safe_path, settings)
        store.save_analysis(plan.analysis_id, plan.model_dump_json(), str(safe_path), file.filename)
        return plan
    except Exception as exc:
        safe_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=f"照片分析失败：{type(exc).__name__}") from exc


@app.post("/api/jobs", response_model=Job)
def create_job(payload: CreateJobRequest, walk_session: str | None = Cookie(default=None)) -> Job:
    _require_session(walk_session)
    record = store.get_analysis(payload.analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="分析结果不存在或已过期")
    plan = PhotoPlan.model_validate_json(record["payload"])
    selected = payload.selected_template or plan.recommended_template
    if selected not in plan.compatible_templates:
        raise HTTPException(status_code=422, detail="所选体验模板与照片规划不兼容")
    with job_creation_lock:
        existing = next((job for job in _active_jobs() if job.analysis_id == payload.analysis_id), None)
        if existing:
            return existing
        if len(_active_jobs()) >= 1:
            raise HTTPException(status_code=429, detail="当前已有生成任务，请稍后再试")
        now = datetime.now(timezone.utc)
        job = Job(
            job_id=uuid.uuid4().hex,
            analysis_id=payload.analysis_id,
            filename=record["filename"],
            generation_mode=payload.generation_mode,
            selected_template=selected,
            state=JobState.queued,
            message="已进入单GPU生成队列",
            created_at=now,
            updated_at=now,
        )
        _save_job(job)
        gpu_queue.submit(_run_job, job.job_id, record, plan)
        return job


@app.post("/api/jobs/{job_id}/retry", response_model=Job)
def retry_job(job_id: str, walk_session: str | None = Cookie(default=None)) -> Job:
    """Create a fresh run after a failed or interrupted run.

    The old job remains as evidence; retrying never overwrites its state or
    silently assumes that a model checkpoint is resumable.
    """

    _require_session(walk_session)
    previous = _load_job(job_id)
    if not previous:
        raise HTTPException(status_code=404, detail="任务不存在")
    if previous.state not in {JobState.failed, JobState.interrupted}:
        raise HTTPException(status_code=409, detail="只有失败或中断任务可以重试")
    record = store.get_analysis(previous.analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="原分析结果不存在或已过期")
    plan = PhotoPlan.model_validate_json(record["payload"])
    with job_creation_lock:
        if _active_jobs():
            raise HTTPException(status_code=429, detail="当前已有生成任务，请稍后再试")
        now = datetime.now(timezone.utc)
        job = Job(
            job_id=uuid.uuid4().hex,
            analysis_id=previous.analysis_id,
            filename=record["filename"],
            generation_mode=previous.generation_mode,
            selected_template=previous.selected_template,
            state=JobState.queued,
            message="失败任务已重新进入单GPU队列",
            created_at=now,
            updated_at=now,
        )
        _save_job(job)
        gpu_queue.submit(_run_job, job.job_id, record, plan)
        return job


def _movement_for_generated_scene(template: SceneTemplate, camera: CameraSpec, scene_bounds: list[list[float]] | None):
    movement = movement_profile(template)
    if not scene_bounds:
        return movement.model_copy(update={"start": camera.position, "ground_follow": False, "ground_y": None, "route_checkpoints": []})
    try:
        lower = [float(value) for value in scene_bounds[0]]
        upper = [float(value) for value in scene_bounds[1]]
        if len(lower) != 3 or len(upper) != 3 or any(lower[i] >= upper[i] for i in range(3)):
            raise ValueError
    except (TypeError, ValueError, IndexError):
        return movement.model_copy(update={"start": camera.position, "ground_follow": False, "ground_y": None, "route_checkpoints": []})
    # AABB is deliberately the first collision boundary. Include the capture
    # origin even when every reconstructed surface lies in front of it.
    extent = [upper[i] - lower[i] for i in range(3)]
    margin = [max(0.2, extent[i] * 0.03) for i in range(3)]
    start = camera.position
    # A terrain reconstruction is a surface, not a sealed walkable volume.
    # Letting the camera descend to the raw mesh AABB puts it underneath the
    # snow surface, where the viewer sees the underside, gray fallback planes,
    # and holes. Keep a small amount of relief below the capture origin, but
    # do not allow a generated terrain scene to become an underground scene.
    if movement.kind == "terrain":
        lower[1] = max(lower[1], float(start[1]) - 0.25)
    bounds = {
        axis: [
            min(lower[i] if movement.kind == "terrain" and axis == "y" else lower[i] - margin[i], float(start[i])),
            max(upper[i] + margin[i], float(start[i])),
        ]
        for i, axis in enumerate(("x", "y", "z"))
    }
    return movement.model_copy(update={
        "start": list(start),
        "bounds": bounds,
        "ground_follow": False,
        "ground_y": None,
        "route_checkpoints": [],
    })


def _write_manifest(scene_id: str, scene_path: Path, template: SceneTemplate, version: str, mock: bool, expires_at: datetime, plan: PhotoPlan, coverage: float | None, camera_payload: dict | None = None, scene_bounds: list[list[float]] | None = None, source_url: str | None = None, quality_metrics: dict[str, object] | None = None, generated_region_note_suffix: str = "") -> None:
    camera = CameraSpec.model_validate(camera_payload) if camera_payload else None
    movement = _movement_for_generated_scene(template, camera, scene_bounds) if camera is not None else movement_profile(template)
    manifest = SceneManifest(
        scene_id=scene_id,
        scene_url=f"/api/scenes/{scene_id}/scene.glb",
        download_url=f"/api/scenes/{scene_id}/scene.glb",
        export_url=f"/api/scenes/{scene_id}/export",
        version=version,
        template=template,
        engine=ENGINE_BY_TEMPLATE[template],
        movement=movement,
        camera=camera,
        source_url=source_url,
        generated_region_note=(("演示几何仅用于流程验证；不可见区域是流程占位，不代表真实空间复原。" if mock else "可见区域使用照片投色；不可见区域目前是深度估计候选几何，纹理补全与结构质量仍待验收。") + generated_region_note_suffix),
        expires_at=expires_at,
        mock=mock,
        experience_kind=plan.experience_kind,
        actions=plan.actions,
        subject_regions=plan.subject_regions,
        capability_status=plan.capability_status,
        coverage=coverage,
        quality_status=("unverified" if mock else str((quality_metrics or {}).get("machine_status", "unverified"))),
        quality_metrics=quality_metrics or {},
    )
    scene_path.parent.joinpath("manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")


def _generate_version(job: Job, record: dict, plan: PhotoPlan, version: str) -> str:
    scene_id = uuid.uuid4().hex
    scene_path = settings.scenes_dir / scene_id / "scene.glb"
    world_scale_override = None
    if version == "full" and job.quick_scene_id:
        quick_manifest_path = _manifest_path(job.quick_scene_id)
        if quick_manifest_path.is_file():
            try:
                quick_manifest = SceneManifest.model_validate_json(quick_manifest_path.read_text(encoding="utf-8"))
                world_scale_override = quick_manifest.camera.world_scale if quick_manifest.camera else None
            except (OSError, ValueError):
                world_scale_override = None
    result = generate_scene(
        Path(record["path"]), scene_path, mock=settings.mock_geometry, settings=settings,
        version=version, template=job.selected_template, world_scale_override=world_scale_override,
    )
    source_path = scene_path.parent / "source.jpg"
    with Image.open(record["path"]) as source_image:
        source_image.convert("RGB").save(source_path, format="JPEG", quality=92, optimize=True)
    coverage = result.get("coverage")
    context_shell = {"enabled": False}
    if settings.experimental_context_shell and not bool(result.get("mock", False)):
        try:
            context_shell = add_context_shell(scene_path, job.selected_template)
        except Exception as exc:
            context_shell = {"enabled": False, "status": "failed", "error": type(exc).__name__}
    quality_metrics = inspect_scene(scene_path)
    quality_metrics["geometry_cleanup"] = {
        "removed_extreme_faces": int(result.get("removed_extreme_faces", 0)),
        "policy": "drop_faces_over_20x_median_edge",
    }
    if context_shell.get("enabled"):
        quality_metrics["context_shell"] = context_shell
    # Coverage is evidence for review, not a hard rejection for an otherwise
    # normal photo. Single-image depth masks often exclude sky, glass, or
    # thin subjects; the UI must surface that uncertainty instead of claiming
    # that the user supplied an unsupported image.
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.scene_ttl_hours)
    _write_manifest(
        scene_id, scene_path, job.selected_template, version, bool(result.get("mock", False)), expires_at,
        plan, float(coverage) if coverage is not None else None, result.get("camera"), result.get("scene_bounds"),
        f"/api/scenes/{scene_id}/source.jpg", quality_metrics,
        (" 侧后方由程序化上下文壳层补足，仅用于有限探索实验，不代表真实空间复原。" if context_shell.get("enabled") else ""),
    )
    return scene_id


def _run_job(job_id: str, record: dict, plan: PhotoPlan) -> None:
    job = _load_job(job_id)
    if not job:
        return
    generation_started = datetime.now(timezone.utc)
    job.generation_started_at = generation_started
    job.validation_status = "not_run"
    _save_job(job)
    try:
        quick_started = time.perf_counter()
        job.state = JobState.quick_generating
        job.progress = 10
        job.message = "正在生成快速版：深度、分层和原图投色"
        _save_job(job)
        quick_id = _generate_version(job, record, plan, "quick")
        job.stage_timings_ms["quick_generation"] = round((time.perf_counter() - quick_started) * 1000)
        job.quick_scene_id = quick_id
        job.scene_id = quick_id
        job.progress = 55
        job.state = JobState.quick_ready
        job.message = "快速版已可体验"
        _save_job(job)
        if job.generation_mode is GenerationMode.quick:
            job.progress = 100
            job.message = "快速版完成"
            job.expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.scene_ttl_hours)
            job.generation_finished_at = datetime.now(timezone.utc)
            _save_job(job)
            return
        full_started = time.perf_counter()
        job.state = JobState.full_generating
        job.progress = 60
        job.message = "正在后台生成完整版候选：重新计算几何（细节补全待质检）"
        _save_job(job)
        full_id = _generate_version(job, record, plan, "full")
        job.stage_timings_ms["full_generation"] = round((time.perf_counter() - full_started) * 1000)
        job.full_scene_id = full_id
        job.scene_id = full_id
        job.progress = 100
        job.state = JobState.full_ready
        job.message = "完整版候选完成；需要对比质检后才能称为质量升级"
        job.generation_finished_at = datetime.now(timezone.utc)
        job.expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.scene_ttl_hours)
        _save_job(job)
        # Keep the normalized source for case review and a possible retry. A
        # later retention action may remove it only after an explicit backup.
    except Exception as exc:
        job.state = JobState.failed
        job.error = type(exc).__name__
        job.message = "生成失败；如果快速版已就绪，它仍可继续体验"
        job.generation_finished_at = datetime.now(timezone.utc)
        _save_job(job)


@app.get("/api/jobs/{job_id}", response_model=Job)
def get_job(job_id: str, walk_session: str | None = Cookie(default=None)) -> Job:
    _require_session(walk_session)
    job = _load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


def _manifest_path(scene_id: str) -> Path:
    return settings.scenes_dir / scene_id / "manifest.json"


def _build_offline_archive(scene_dir: Path) -> bytes:
    """Build a self-contained viewer package without network references."""

    project_root = Path(__file__).resolve().parents[2]
    three_module = project_root / "frontend" / "node_modules" / "three" / "build" / "three.module.js"
    gltf_loader = project_root / "frontend" / "node_modules" / "three" / "examples" / "jsm" / "loaders" / "GLTFLoader.js"
    buffer_geometry_utils = project_root / "frontend" / "node_modules" / "three" / "examples" / "jsm" / "utils" / "BufferGeometryUtils.js"
    if not all(path.is_file() for path in (three_module, gltf_loader, buffer_geometry_utils)):
        raise FileNotFoundError("离线查看器依赖未准备好")
    loader_text = gltf_loader.read_text(encoding="utf-8").replace("../utils/BufferGeometryUtils.js", "./BufferGeometryUtils.js")
    buffer_utils_text = buffer_geometry_utils.read_text(encoding="utf-8")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(scene_dir / "scene.glb", "scene.glb")
        archive.write(scene_dir / "manifest.json", "manifest.json")
        archive.writestr("index.html", _OFFLINE_VIEWER_HTML)
        archive.write(three_module, "three.module.js")
        archive.writestr("GLTFLoader.js", loader_text)
        archive.writestr("BufferGeometryUtils.js", buffer_utils_text)
        archive.writestr("README.txt", "走进照片离线场景包\n\n双击 index.html 打开基础查看器；它不需要模型权重、API、CDN 或联网。场景包不包含原始照片；scene.glb 可能含有从原照片生成的纹理。照片不可见区域是估计或程序化创作，不代表真实空间复原。\n")
    return buffer.getvalue()


@app.get("/api/scenes/{scene_id}/manifest", response_model=SceneManifest)
def get_manifest(scene_id: str, walk_session: str | None = Cookie(default=None)) -> SceneManifest:
    _require_session(walk_session)
    path = _manifest_path(scene_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="场景不存在或已过期")
    manifest = SceneManifest.model_validate_json(path.read_text(encoding="utf-8"))
    if manifest.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="场景已过期")
    return manifest


@app.get("/api/scenes/{scene_id}/scene.glb")
def get_scene(scene_id: str, walk_session: str | None = Cookie(default=None)):
    _require_session(walk_session)
    path = settings.scenes_dir / scene_id / "scene.glb"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="场景不存在")
    return FileResponse(path, media_type="model/gltf-binary", filename="scene.glb")


@app.get("/api/scenes/{scene_id}/source.jpg")
def get_source(scene_id: str, walk_session: str | None = Cookie(default=None)):
    _require_session(walk_session)
    path = settings.scenes_dir / scene_id / "source.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="原图背景不存在")
    return FileResponse(path, media_type="image/jpeg", filename="source.jpg")


@app.get("/api/scenes/{scene_id}/export")
def export_scene(scene_id: str, walk_session: str | None = Cookie(default=None)):
    _require_session(walk_session)
    scene_dir = settings.scenes_dir / scene_id
    if not (scene_dir / "scene.glb").is_file() or not (scene_dir / "manifest.json").is_file():
        raise HTTPException(status_code=404, detail="场景不存在")
    try:
        archive_bytes = _build_offline_archive(scene_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return StreamingResponse(BytesIO(archive_bytes), media_type="application/zip", headers={"Content-Disposition": f"attachment; filename=walk-scene-{scene_id[:8]}.zip"})
