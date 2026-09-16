from __future__ import annotations

import asyncio
import base64
import hashlib
import json
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
from pydantic import BaseModel, Field

from app.config import settings
from app.models import CameraSpec, GenerationMode, Job, JobState, MovementProfile, PhotoPlan, RegionConfirmation, SceneManifest, SceneTemplate
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
<style>html,body{margin:0;height:100%;background:#101022;color:#eee;font:14px system-ui,sans-serif}#hud{position:fixed;z-index:2;left:14px;top:14px;padding:10px 12px;border-radius:10px;background:#111126dd;max-width:380px}#view{width:100%;height:100%;display:block;cursor:grab;touch-action:none}</style></head>
<body><div id="hud">正在加载离线场景…<br><small>拖动环顾 · WASD移动 · R回到起点</small></div><canvas id="view"></canvas>
<script type="module">
__THREE_INLINE__
__BUFFER_UTILS_INLINE__
__GLTF_LOADER_INLINE__
const manifest=__MANIFEST_JSON__;
const glbBytes=Uint8Array.from(atob("__GLB_BASE64__"),character=>character.charCodeAt(0));
const canvas=document.querySelector('#view'),hud=document.querySelector('#hud');canvas.tabIndex=0;
const renderer=new WebGLRenderer({canvas,antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setClearColor('#263044',1);
const scene=new Scene();scene.background=new Color('#263044');
scene.add(new HemisphereLight('#f8fbff','#7d8798',1.2));const keyLight=new DirectionalLight('#ffffff',1.2);keyLight.position.set(4,8,4);scene.add(keyLight);
const camera=new PerspectiveCamera(68,1,.01,200);let start=manifest.movement.start;let yaw=0,pitch=0;const keys=new Set();let dragging=false,last=[0,0],active=false;let movement=manifest.movement,flying=false;const collisionBoxes=movement.collision_boxes||[];const collisionRadius=movement.collision_radius||0;
function fitCameraFov(){if(!manifest.camera)return;const aspect=Math.max(innerWidth/Math.max(innerHeight,1),.1);const imageAspect=manifest.camera.image_size?.[1]?manifest.camera.image_size[0]/manifest.camera.image_size[1]:aspect;if(manifest.camera.fov_x!=null&&manifest.camera.fov_y!=null){const rad=value=>value*Math.PI/180;const deg=value=>value*180/Math.PI;camera.fov=aspect>=imageAspect?deg(2*Math.atan(Math.tan(rad(manifest.camera.fov_x)/2)/aspect)):manifest.camera.fov_y}else camera.fov=manifest.camera.fov_y||camera.fov;camera.aspect=aspect;camera.updateProjectionMatrix()}
camera.position.set(...start);if(manifest.camera){camera.near=manifest.camera.near;camera.far=manifest.camera.far;fitCameraFov()};
window.addEventListener('keydown',event=>{if(!active)return;const key=event.key.toLowerCase();if([' ','w','a','s','d','c','f','r','arrowup','arrowdown','arrowleft','arrowright'].includes(key))event.preventDefault();if(key==='f'&&event.repeat)return;keys.add(key);if(key==='f'&&movement.allow_flight)flying=!flying;if(key==='r'){camera.position.set(...start);yaw=0;pitch=0;flying=false}});window.addEventListener('keyup',event=>{if(active)keys.delete(event.key.toLowerCase())});window.addEventListener('blur',()=>keys.clear());document.addEventListener('visibilitychange',()=>keys.clear());canvas.addEventListener('focus',()=>active=true);canvas.addEventListener('blur',()=>{active=false;keys.clear()});
canvas.addEventListener('pointerdown',event=>{canvas.focus();dragging=true;last=[event.clientX,event.clientY];canvas.setPointerCapture(event.pointerId)});canvas.addEventListener('pointerup',()=>dragging=false);canvas.addEventListener('pointerleave',()=>dragging=false);canvas.addEventListener('pointermove',event=>{if(!dragging)return;yaw-=(event.clientX-last[0])*.005;pitch=Math.max(-1.35,Math.min(1.35,pitch-(event.clientY-last[1])*.005));last=[event.clientX,event.clientY]});
function collides(x,z){return collisionBoxes.some(box=>{const xb=box.bounds?.x,zb=box.bounds?.z;if(!xb||!zb||xb.length!==2||zb.length!==2)return false;return x>=xb[0]-collisionRadius&&x<=xb[1]+collisionRadius&&z>=zb[0]-collisionRadius&&z<=zb[1]+collisionRadius})}
function moveHorizontal(dx,dz){const steps=Math.max(1,Math.ceil(Math.max(Math.abs(dx),Math.abs(dz))/.12));let x=camera.position.x,z=camera.position.z;const sx=dx/steps,sz=dz/steps;for(let i=0;i<steps;i++){const nx=x+sx,nz=z+sz;if(!collides(nx,nz)){x=nx;z=nz;continue}if(!collides(nx,z))x=nx;if(!collides(x,nz))z=nz}return [x,z]}
function resize(){const w=innerWidth,h=innerHeight;renderer.setSize(w,h,false);camera.aspect=w/Math.max(h,1);fitCameraFov()}addEventListener('resize',resize);resize();
const hudHint=`拖动环顾 · WASD移动 · R回到起点${movement.allow_flight?' · F飞行 · 空格上升 · C下降':''}`;let loadFailed=false;function updateHud(){if(loadFailed)return;hud.innerHTML=`<b>${manifest.template}</b> · ${manifest.version}<br><small>${hudHint} · 位置 ${camera.position.x.toFixed(2)} / ${camera.position.y.toFixed(2)} / ${camera.position.z.toFixed(2)}</small>`}updateHud();
new GLTFLoader().parse(glbBytes.buffer,'',gltf=>{gltf.scene.traverse(object=>{const mesh=object;const material=mesh.material;if(!material)return;const materials=Array.isArray(material)?material:[material];for(const entry of materials){entry.side=DoubleSide;if('emissive' in entry&&'color' in entry){entry.emissive.copy(entry.color);entry.emissiveIntensity=.07}entry.needsUpdate=true}});scene.add(gltf.scene)},undefined,error=>{loadFailed=true;hud.textContent='离线场景加载失败：'+error.message});
const clock=new Clock();function loop(){requestAnimationFrame(loop);const d=Math.min(clock.getDelta(),.05);const f=Number(keys.has('w')||keys.has('arrowup'))-Number(keys.has('s')||keys.has('arrowdown'));const s=Number(keys.has('d')||keys.has('arrowright'))-Number(keys.has('a')||keys.has('arrowleft'));const len=Math.hypot(f,s)||1;const speed=(flying&&movement.allow_flight?movement.fly_speed:movement.walk_speed||1.8)*d;const dx=(-Math.sin(yaw)*(f/len)+Math.cos(yaw)*(s/len))*speed;const dz=(-Math.cos(yaw)*(f/len)-Math.sin(yaw)*(s/len))*speed;const next=moveHorizontal(dx,dz);camera.position.x=next[0];camera.position.z=next[1];if(flying&&movement.allow_flight)camera.position.y+=(Number(keys.has(' '))-Number(keys.has('c')))*speed;for(const axis of ['x','y','z']){const bounds=movement.bounds[axis];if(bounds)camera.position[axis]=Math.max(bounds[0],Math.min(bounds[1],camera.position[axis]))}camera.rotation.set(pitch,yaw,0,'YXZ');updateHud();renderer.render(scene,camera)}loop();
</script></body></html>"""


class AccessRequest(BaseModel):
    code: str = ""


class AccessResponse(BaseModel):
    ok: bool


class CreateJobRequest(BaseModel):
    analysis_id: str
    selected_template: SceneTemplate | None = None
    generation_mode: GenerationMode = GenerationMode.progressive
    quality_route: bool = True
    region_confirmations: list[RegionConfirmation] = Field(default_factory=list)


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _cancel_job_if_requested(job: Job, scene_id: str | None = None) -> bool:
    """Finish a cooperative cancellation without promoting a candidate."""

    if not job.cancel_requested:
        return False
    if scene_id and not job.quick_scene_id:
        job.quick_scene_id = scene_id
    if scene_id and job.quick_scene_id == scene_id:
        job.scene_id = scene_id
    elif job.quick_scene_id:
        job.scene_id = job.quick_scene_id
    job.state = JobState.cancelled
    job.error = "CANCELLED"
    job.message = "任务已取消；已完成的快速结果仍可查看"
    job.generation_finished_at = datetime.now(timezone.utc)
    job.expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.scene_ttl_hours)
    _save_job(job)
    return True


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
        "coarse_scene_enabled": settings.coarse_scene_enabled,
        "quality_scene_enabled": settings.quality_scene_enabled,
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
        plan.input_sha256 = hashlib.sha256(content).hexdigest()
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
            quality_route=payload.quality_route,
            region_confirmations=payload.region_confirmations,
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
    if previous.state not in {JobState.failed, JobState.interrupted, JobState.cancelled}:
        raise HTTPException(status_code=409, detail="只有失败、中断或取消任务可以重试")
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
            quality_route=previous.quality_route,
            region_confirmations=previous.region_confirmations,
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


def _write_manifest(
    scene_id: str,
    scene_path: Path,
    template: SceneTemplate,
    version: str,
    mock: bool,
    expires_at: datetime,
    plan: PhotoPlan,
    coverage: float | None,
    camera_payload: dict | None = None,
    scene_bounds: list[list[float]] | None = None,
    source_url: str | None = None,
    quality_metrics: dict[str, object] | None = None,
    generated_region_note_suffix: str = "",
    *,
    input_sha256: str | None = None,
    provider_version: str | None = None,
    coordinate_frame_id: str | None = None,
    resource_manifest: list[str] | None = None,
    collision_resource: str | None = None,
    acceptance_evidence: list[str] | None = None,
    movement_payload: dict | None = None,
    generation_source: str = "legacy",
    fallback_reason: str | None = None,
    layout_version: str | None = None,
    estimated_scale: float | None = None,
    quality_route: bool = False,
    manual_assisted: bool = False,
    manual_region_sha256: str | None = None,
    photo_supported_regions: list[str] | None = None,
    generated_regions: list[str] | None = None,
) -> None:
    camera = CameraSpec.model_validate(camera_payload) if camera_payload else None
    if movement_payload is not None:
        movement = MovementProfile.model_validate(movement_payload)
    else:
        movement = _movement_for_generated_scene(template, camera, scene_bounds) if camera is not None else movement_profile(template)
    if generation_source == "procedural_coarse":
        region_note = "自动粗模：墙、地面、家具或地标由参数化场景生成；照片作为展示面与配色参考，不代表真实空间复原。"
    elif generation_source == "photo_supported_quality":
        region_note = "照片支持质量路线：MoGe 保留照片投色表面；新增结构与不可见区域为有范围的估计补全，仍需视觉验收。"
    elif mock:
        region_note = "演示几何仅用于流程验证；不可见区域是流程占位，不代表真实空间复原。"
    else:
        region_note = "可见区域使用照片投色；不可见区域目前是深度估计候选几何，纹理补全与结构质量仍待验收。"
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
        generated_region_note=region_note + generated_region_note_suffix,
        expires_at=expires_at,
        mock=mock,
        experience_kind=plan.experience_kind,
        actions=plan.actions,
        subject_regions=plan.subject_regions,
        capability_status=plan.capability_status,
        coverage=coverage,
        quality_status=("unverified" if mock else str((quality_metrics or {}).get("machine_status", "unverified"))),
        quality_metrics=quality_metrics or {},
        input_sha256=input_sha256,
        provider_version=provider_version,
        coordinate_frame_id=coordinate_frame_id or (camera.coordinate_frame_id if camera else None),
        resource_manifest=list(resource_manifest or []),
        collision_resource=collision_resource,
        acceptance_evidence=list(acceptance_evidence or []),
        generation_source=generation_source,
        fallback_reason=fallback_reason,
        layout_version=layout_version,
        estimated_scale=estimated_scale,
        quality_route=quality_route,
        manual_assisted=manual_assisted,
        manual_region_sha256=manual_region_sha256,
        photo_supported_regions=list(photo_supported_regions or []),
        generated_regions=list(generated_regions or []),
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
    manual_regions_payload = [region.model_dump(mode="json") for region in job.region_confirmations]
    manual_region_sha256 = hashlib.sha256(
        json.dumps(manual_regions_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest() if manual_regions_payload else None
    result = generate_scene(
        Path(record["path"]), scene_path, mock=settings.mock_geometry, settings=settings,
        version=version, template=job.selected_template, world_scale_override=world_scale_override,
        manual_regions=job.region_confirmations, quality_route=job.quality_route,
    )
    source_path = scene_path.parent / "source.jpg"
    with Image.open(record["path"]) as source_image:
        source_image.convert("RGB").save(source_path, format="JPEG", quality=92, optimize=True)
    coverage = result.get("coverage")
    context_shell = {"enabled": False}
    if settings.experimental_context_shell and not bool(result.get("mock", False)) and result.get("scene_source") not in {"procedural_coarse", "photo_supported_quality"}:
        try:
            context_shell = add_context_shell(scene_path, job.selected_template)
        except Exception as exc:
            context_shell = {"enabled": False, "status": "failed", "error": type(exc).__name__}
    quality_metrics = inspect_scene(scene_path)
    quality_metrics["geometry_cleanup"] = {
        "removed_extreme_faces": int(result.get("removed_extreme_faces", 0)),
        "policy": "drop_faces_over_20x_median_edge",
    }
    quality_metrics["generation_route"] = {
        "quality_route": job.quality_route,
        "scene_source": result.get("scene_source", "legacy"),
        "quality_route_error": result.get("quality_route_error"),
        "manual_assisted": bool(result.get("manual_assisted", manual_regions_payload)),
    }
    if result.get("stage_timings_ms"):
        quality_metrics["stage_timings_ms"] = dict(result["stage_timings_ms"])
    if context_shell.get("enabled"):
        quality_metrics["context_shell"] = context_shell
    resource_manifest = ["scene.glb", "source.jpg"]
    for evidence_name in [*result.get("evidence_files", []), *result.get("resource_files", [])]:
        evidence_path = scene_path.parent / str(evidence_name)
        if evidence_path.is_file() and evidence_path.name not in resource_manifest:
            resource_manifest.append(evidence_path.name)
    provider_version = str(result.get("provider_version") or (
        "demo-geometry-v1"
        if bool(result.get("mock", False))
        else f"moge-{settings.moge_version}:{settings.moge_pretrained}"
    ))
    camera_payload = result.get("camera")
    # Coverage is evidence for review, not a hard rejection for an otherwise
    # normal photo. Single-image depth masks often exclude sky, glass, or
    # thin subjects; the UI must surface that uncertainty instead of claiming
    # that the user supplied an unsupported image.
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.scene_ttl_hours)
    _write_manifest(
        scene_id, scene_path, job.selected_template, version, bool(result.get("mock", False)), expires_at,
        plan, float(coverage) if coverage is not None else None, camera_payload, result.get("scene_bounds"),
        f"/api/scenes/{scene_id}/source.jpg", quality_metrics,
        ((" " + str(result.get("generated_region_note"))) if result.get("generated_region_note") else "")
        + (" 侧后方由程序化上下文壳层补足，仅用于有限探索实验，不代表真实空间复原。" if context_shell.get("enabled") else ""),
        input_sha256=plan.input_sha256 or _sha256_file(Path(record["path"])),
        provider_version=provider_version,
        coordinate_frame_id=(camera_payload or {}).get("coordinate_frame_id"),
        resource_manifest=resource_manifest,
        collision_resource=str(result["collision_resource"]) if result.get("collision_resource") else None,
        acceptance_evidence=[],
        movement_payload=result.get("movement"),
        generation_source=str(result.get("scene_source", "legacy")),
        fallback_reason=result.get("fallback_reason"),
        layout_version=result.get("layout_version"),
        estimated_scale=float(result["estimated_scale"]) if result.get("estimated_scale") is not None else None,
        quality_route=job.quality_route,
        manual_assisted=bool(result.get("manual_assisted", manual_regions_payload)),
        manual_region_sha256=manual_region_sha256,
        photo_supported_regions=list(result.get("photo_supported_regions", [])),
        generated_regions=list(result.get("generated_regions", [])),
    )
    return scene_id


def _scene_quality_status(scene_id: str) -> str:
    """Read the machine result without turning missing data into a pass."""

    try:
        manifest = SceneManifest.model_validate_json(_manifest_path(scene_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unverified"
    return manifest.quality_status or "unverified"


def _compare_upgrade_versions(quick_scene_id: str | None, full_scene_id: str | None) -> dict[str, object]:
    """Return a conservative quick/full promotion decision with reasons."""

    if not quick_scene_id or not full_scene_id:
        return {
            "measurable_upgrade_candidate": False,
            "machine_status": "unverified",
            "warnings": ["quick 或 full 场景编号缺失，不能安全切换"],
        }
    quick_manifest = _manifest_path(quick_scene_id)
    full_manifest = _manifest_path(full_scene_id)
    if not quick_manifest.is_file() or not full_manifest.is_file():
        return {
            "measurable_upgrade_candidate": False,
            "machine_status": "unverified",
            "warnings": ["quick/full manifest 缺失，不能安全切换"],
        }
    try:
        from scripts.compare_scene_versions import compare

        return compare(quick_manifest, full_manifest)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {
            "measurable_upgrade_candidate": False,
            "machine_status": "failed",
            "warnings": [f"quick/full 对比失败：{type(exc).__name__}"],
        }


def _record_upgrade_comparison(scene_id: str, comparison: dict[str, object]) -> None:
    """Persist the decision beside the full candidate for later review."""

    path = _manifest_path(scene_id)
    if not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        metrics = payload.setdefault("quality_metrics", {})
        metrics["upgrade_comparison"] = comparison
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        # The candidate remains addressable; absence of this diagnostic must
        # never become permission to promote it.
        return


def _record_quality_status(job: Job, quality_status: str) -> None:
    """Expose machine quality separately from the generation lifecycle."""

    job.quality_status = quality_status or "unverified"
    if job.quality_status == "failed":
        job.validation_status = "failed"
    elif job.quality_status == "needs_visual_review":
        job.validation_status = "needs_review"
    elif job.quality_status == "passed":
        job.validation_status = "passed"
    else:
        job.validation_status = "not_run"


def _run_job(job_id: str, record: dict, plan: PhotoPlan) -> None:
    job = _load_job(job_id)
    if not job:
        return
    if _cancel_job_if_requested(job):
        return
    generation_started = datetime.now(timezone.utc)
    job.generation_started_at = generation_started
    job.validation_status = "not_run"
    job.quality_status = "unverified"
    _save_job(job)
    try:
        if job.quality_route:
            quality_started = time.perf_counter()
            job.state = JobState.quick_generating
            job.progress = 8
            job.message = "质量路线：分析、深度与相机"
            _save_job(job)
            quality_id = _generate_version(job, record, plan, "full")
            job.stage_timings_ms["quality_generation"] = round((time.perf_counter() - quality_started) * 1000)
            job.quick_scene_id = quality_id
            job.scene_id = quality_id
            if _cancel_job_if_requested(job, quality_id):
                return
            quality_status = _scene_quality_status(quality_id)
            _record_quality_status(job, quality_status)
            if quality_status == "failed":
                job.scene_id = None
                job.progress = 100
                job.state = JobState.failed
                job.error = "QUALITY_MACHINE_CHECK_FAILED"
                job.message = "质量路线机器结构检查失败；候选已保留供诊断"
            else:
                job.progress = 100
                job.state = JobState.quick_ready
                job.message = "质量路线完成；照片表面与结构候选仍需视觉复核"
            job.generation_finished_at = datetime.now(timezone.utc)
            job.expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.scene_ttl_hours)
            _save_job(job)
            return
        quick_started = time.perf_counter()
        job.state = JobState.quick_generating
        job.progress = 10
        job.message = "正在生成快速版：深度、分层和原图投色"
        _save_job(job)
        quick_id = _generate_version(job, record, plan, "quick")
        job.stage_timings_ms["quick_generation"] = round((time.perf_counter() - quick_started) * 1000)
        job.quick_scene_id = quick_id
        if _cancel_job_if_requested(job, quick_id):
            return
        quick_quality = _scene_quality_status(quick_id)
        _record_quality_status(job, quick_quality)
        if quick_quality == "failed":
            job.scene_id = None
            job.progress = 100
            job.state = JobState.failed
            job.error = "QUICK_MACHINE_QUALITY_FAILED"
            job.message = "快速版机器结构检查失败，未提供可用结果"
            job.generation_finished_at = datetime.now(timezone.utc)
            _save_job(job)
            return
        job.scene_id = quick_id
        job.progress = 55
        job.state = JobState.quick_ready
        job.message = "快速版已可体验"
        _save_job(job)
        if _cancel_job_if_requested(job, quick_id):
            return
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
        full_quality = _scene_quality_status(full_id)
        _record_quality_status(job, full_quality)
        upgrade_comparison = _compare_upgrade_versions(job.quick_scene_id, full_id)
        _record_upgrade_comparison(full_id, upgrade_comparison)
        if _cancel_job_if_requested(job, full_id):
            return
        if full_quality == "failed":
            # Keep the quick result addressable and visible; the failed full
            # candidate remains on disk for evidence but is not promoted.
            job.scene_id = job.quick_scene_id
            job.progress = 55
            job.state = JobState.quick_ready
            job.error = "FULL_MACHINE_QUALITY_FAILED"
            job.message = "完整版机器结构检查失败，保留快速版"
            job.generation_finished_at = datetime.now(timezone.utc)
            job.expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.scene_ttl_hours)
            _save_job(job)
            return
        if not bool(upgrade_comparison.get("measurable_upgrade_candidate")):
            # A generated full candidate is retained for review, but the
            # viewer stays on the quick scene until quality and route evidence
            # prove a safe, measurable improvement.
            job.scene_id = job.quick_scene_id
            job.progress = 55
            job.state = JobState.quick_ready
            job.error = "FULL_UPGRADE_NOT_PROMOTED"
            job.message = "完整版候选完成，但未通过安全升级条件，保留快速版"
            job.generation_finished_at = datetime.now(timezone.utc)
            job.expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.scene_ttl_hours)
            _save_job(job)
            return
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


@app.post("/api/jobs/{job_id}/cancel", response_model=Job)
def cancel_job(job_id: str, walk_session: str | None = Cookie(default=None)) -> Job:
    """Request a cooperative cancellation while preserving the job record."""

    _require_session(walk_session)
    job = _load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.state is JobState.cancelled:
        return job
    if job.state not in {JobState.queued, JobState.quick_generating, JobState.full_generating}:
        raise HTTPException(status_code=409, detail="当前任务不在可取消阶段")
    job.cancel_requested = True
    if job.state is JobState.queued:
        _cancel_job_if_requested(job)
    else:
        job.message = "已请求取消；当前 GPU 阶段结束后停止"
        _save_job(job)
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
    three_text = three_module.read_text(encoding="utf-8")
    buffer_utils_text = buffer_geometry_utils.read_text(encoding="utf-8")
    loader_text = gltf_loader.read_text(encoding="utf-8")

    def strip_exports(source: str) -> str:
        marker = "\nexport {"
        index = source.rfind(marker)
        if index < 0:
            raise ValueError("离线查看器依赖缺少可移除的 export 块")
        return source[:index]

    three_inline = strip_exports(three_text)
    buffer_import_end = buffer_utils_text.index("} from 'three';") + len("} from 'three';")
    buffer_inline = strip_exports(buffer_utils_text[buffer_import_end:])
    loader_import_end = loader_text.index("} from 'three';") + len("} from 'three';")
    loader_inline = loader_text[loader_import_end:]
    loader_inline = loader_inline.replace(
        "import { toTrianglesDrawMode } from '../utils/BufferGeometryUtils.js';", ""
    )
    loader_inline = loader_inline.replace("_identityMatrix", "_gltfIdentityMatrix")
    loader_inline = strip_exports(loader_inline)
    manifest_json = json.dumps(
        json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8")),
        ensure_ascii=False,
    ).replace("<", "\\u003c")
    glb_base64 = base64.b64encode((scene_dir / "scene.glb").read_bytes()).decode("ascii")
    offline_html = (
        _OFFLINE_VIEWER_HTML
        .replace("__THREE_INLINE__", three_inline)
        .replace("__BUFFER_UTILS_INLINE__", buffer_inline)
        .replace("__GLTF_LOADER_INLINE__", loader_inline)
        .replace("__MANIFEST_JSON__", manifest_json)
        .replace("__GLB_BASE64__", glb_base64)
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(scene_dir / "scene.glb", "scene.glb")
        archive.write(scene_dir / "manifest.json", "manifest.json")
        for resource_name in ("layout.json", "collision.json"):
            resource_path = scene_dir / resource_name
            if resource_path.is_file():
                archive.write(resource_path, resource_name)
        archive.writestr("index.html", offline_html)
        archive.write(three_module, "three.module.js")
        archive.writestr("GLTFLoader.js", loader_text)
        archive.writestr("BufferGeometryUtils.js", buffer_utils_text)
        archive.writestr("README.txt", "走进照片离线场景包\n\n双击 index.html 打开基础查看器；它不需要模型权重、API、CDN 或联网。场景包不包含原始照片；scene.glb 可能含有从原照片生成的纹理。照片不可见区域是估计或程序化创作，不代表真实空间复原。若 manifest 含有 collision_boxes，离线查看器会使用它们阻挡墙体和简化家具。\n")
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
