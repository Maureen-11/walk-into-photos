import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import * as THREE from "three";

type Template = string;
type ExperienceKind = "spatial_scene" | "interactive_subject" | "still_fallback";
type Action = {
  action_id: string;
  label: string;
  trigger: "mouse_stroke" | "click" | "future_gesture";
  target_region_id?: string;
  asset_url?: string;
  status: "available" | "experimental" | "unverified" | "unavailable";
  cooldown_ms: number;
  hint?: string;
};
type SubjectRegion = { region_id: string; label: string; x?: number; y?: number; width?: number; height?: number; confidence?: number; occluded?: boolean };
type Plan = {
  analysis_id: string;
  category: string;
  title: string;
  summary: string;
  recommended_template: Template;
  compatible_templates: Template[];
  rationale: string;
  scene_description: string;
  warnings: string[];
  estimated_quick_seconds: number;
  estimated_full_seconds: number;
  planner_backend: string;
  experimental: boolean;
  mock: boolean;
  experience_kind?: ExperienceKind;
  capability_status?: Action["status"];
  subject_regions?: SubjectRegion[];
  actions?: Action[];
  capability_notes?: string[];
};
type Job = {
  job_id: string;
  state: string;
  progress: number;
  progress_kind?: string;
  message: string;
  selected_template: Template;
  generation_mode: "quick" | "full" | "progressive";
  quick_scene_id?: string;
  full_scene_id?: string;
  scene_id?: string;
  error?: string;
  validation_status?: "not_run" | "passed" | "failed" | "needs_review";
  stage_timings_ms?: Record<string, number>;
};
type Movement = { kind: string; start: number[]; bounds: Record<string, number[]>; walk_speed: number; fly_speed: number; allow_flight: boolean; ground_follow?: boolean; ground_y?: number; collision_radius?: number; route_checkpoints?: number[][] };
type CameraSpec = { position: number[]; intrinsics?: number[][]; image_size?: number[]; camera_to_world?: number[][]; world_scale: number; near: number; far: number; fov_x?: number; fov_y?: number; coordinate_frame_id: string };
type Manifest = { scene_id: string; scene_url: string; export_url: string; version: string; template: Template; engine?: string; movement: Movement; camera?: CameraSpec; source_url?: string; generated_region_note: string; mock: boolean; experience_kind?: ExperienceKind; actions?: Action[]; subject_regions?: SubjectRegion[]; capability_status?: Action["status"]; coverage?: number | null; quality_status?: string; quality_metrics?: Record<string, unknown> };

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");
const apiUrl = (path: string) => path.startsWith("http://") || path.startsWith("https://") ? path : `${API_BASE_URL}${path}`;

const api = async (url: string, init?: RequestInit) => {
  const response = await fetch(apiUrl(url), { credentials: "include", ...init });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail ?? "请求失败");
  return body;
};

function SceneContent({ objectUrl, manifest, lookRef, onReset, onPosition }: { objectUrl: string; manifest: Manifest; lookRef: React.MutableRefObject<{ yaw: number; pitch: number }>; onReset: () => void; onPosition: (position: number[]) => void }) {
  const { scene } = useGLTF(objectUrl);
  const { camera } = useThree();
  const keys = useRef(new Set<string>());
  const flying = useRef(false);
  const lastPositionReport = useRef(0);
  const lastTerrainCollisionCheck = useRef(0);
  const lastValidTerrainPosition = useRef(new THREE.Vector3());
  const movement = manifest.movement;
  const terrainCollisionMeshes = useMemo(() => {
    if (movement.kind !== "terrain") return [] as THREE.Object3D[];
    const meshes: THREE.Object3D[] = [];
    scene.traverse((object) => {
      const mesh = object as THREE.Mesh;
      if (mesh.isMesh && !object.name.startsWith("context-")) meshes.push(object);
    });
    return meshes;
  }, [movement.kind, scene]);
  const terrainRaycaster = useMemo(() => new THREE.Raycaster(), []);
  const terrainRayOrigin = useMemo(() => new THREE.Vector3(), []);
  const terrainRayDirection = useMemo(() => new THREE.Vector3(0, -1, 0), []);
  useEffect(() => {
    // The experimental indoor/terrain context shell is a thin, camera-facing
    // enclosure. Its inner faces must remain visible while the viewer is
    // inside; otherwise WebGL back-face culling turns the side view into a
    // black void. Apply this only to the loaded scene materials, without
    // changing the geometry or claiming that unseen space was reconstructed.
    scene.traverse((object) => {
      const mesh = object as THREE.Mesh;
      const material = mesh.material;
      if (!material) return;
      const materials = Array.isArray(material) ? material : [material];
      for (const entry of materials) {
        entry.side = THREE.DoubleSide;
        entry.needsUpdate = true;
      }
    });
  }, [scene]);
  useEffect(() => {
    const down = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      // These keys belong to the scene controller. In particular, Space has
      // a browser-level default action (scroll the document) which otherwise
      // runs at the same time as the flight controller moves the camera.
      const sceneKeys = new Set([" ", "w", "a", "s", "d", "c", "f", "r", "arrowup", "arrowdown", "arrowleft", "arrowright"]);
      if (sceneKeys.has(key)) event.preventDefault();
      keys.current.add(key);
      if (key === "f" && movement.allow_flight) flying.current = !flying.current;
      if (key === "r") {
        camera.position.set(...(movement.start as [number, number, number]));
        lookRef.current = { yaw: 0, pitch: 0 };
        onReset();
      }
    };
    const up = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      if (key === " ") event.preventDefault();
      keys.current.delete(key);
    };
    const clearKeys = () => keys.current.clear();
    window.addEventListener("keydown", down, { passive: false }); window.addEventListener("keyup", up, { passive: false });
    window.addEventListener("blur", clearKeys); document.addEventListener("visibilitychange", clearKeys);
    // Keep the user's position when a progressive full scene swaps in. A new
    // SceneContent instance still starts at the manifest origin.
    if (camera.userData.walkIntoPhotosInitialized !== true) {
      camera.position.set(...(movement.start as [number, number, number]));
      camera.userData.walkIntoPhotosInitialized = true;
    }
    lastValidTerrainPosition.current.set(camera.position.x, camera.position.y, camera.position.z);
    if (manifest.camera && camera instanceof THREE.PerspectiveCamera) {
      camera.fov = manifest.camera.fov_y ?? camera.fov;
      camera.near = manifest.camera.near;
      camera.far = manifest.camera.far;
      camera.updateProjectionMatrix();
    }
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); window.removeEventListener("blur", clearKeys); document.removeEventListener("visibilitychange", clearKeys); };
  }, [camera, manifest.camera, movement, onReset]);
  useFrame((_, delta) => {
    const forward = Number(keys.current.has("w") || keys.current.has("arrowup")) - Number(keys.current.has("s") || keys.current.has("arrowdown"));
    const sideways = Number(keys.current.has("d") || keys.current.has("arrowright")) - Number(keys.current.has("a") || keys.current.has("arrowleft"));
    const directionLength = Math.hypot(forward, sideways) || 1;
    const frameDelta = Math.min(Math.max(delta, 0), 0.05);
    const speed = (flying.current ? movement.fly_speed : movement.walk_speed) * frameDelta;
    const yaw = lookRef.current.yaw;
    camera.position.x += Math.sin(yaw) * (forward / directionLength) * speed + Math.cos(yaw) * (sideways / directionLength) * speed;
    camera.position.z += -Math.cos(yaw) * (forward / directionLength) * speed + Math.sin(yaw) * (sideways / directionLength) * speed;
    if (flying.current && movement.allow_flight) {
      const vertical = Number(keys.current.has(" ")) - Number(keys.current.has("c"));
      camera.position.y += vertical * speed;
    } else if (movement.ground_follow && movement.ground_y != null) {
      camera.position.y = movement.ground_y;
    }
    camera.position.x = THREE.MathUtils.clamp(camera.position.x, movement.bounds.x[0], movement.bounds.x[1]);
    // Older manifests may still contain the raw terrain AABB. Apply the same
    // safety floor client-side so an already generated scene cannot descend
    // underneath the reconstructed surface while the backend is upgraded.
    const terrainFloor = movement.kind === "terrain"
      ? Math.max(movement.bounds.y[0], movement.start[1] - 0.25)
      : movement.bounds.y[0];
    camera.position.y = THREE.MathUtils.clamp(camera.position.y, terrainFloor, movement.bounds.y[1]);
    camera.position.z = THREE.MathUtils.clamp(camera.position.z, movement.bounds.z[0], movement.bounds.z[1]);
    const now = performance.now();
    if (movement.kind === "terrain" && terrainCollisionMeshes.length && now - lastTerrainCollisionCheck.current > 80) {
      lastTerrainCollisionCheck.current = now;
      // The reconstructed terrain is not a sealed volume. A downward ray is
      // a conservative local floor: if the camera crosses a visible triangle,
      // lift it just above that triangle instead of showing the mesh underside.
      terrainRayOrigin.set(camera.position.x, movement.bounds.y[1] + 2, camera.position.z);
      terrainRaycaster.set(terrainRayOrigin, terrainRayDirection);
      const hit = terrainRaycaster.intersectObjects(terrainCollisionMeshes, true)[0];
      if (hit && Number.isFinite(hit.point.y)) {
        const clearance = flying.current ? 0.12 : 0.2;
        camera.position.y = Math.max(camera.position.y, hit.point.y + clearance);
        lastValidTerrainPosition.current.set(camera.position.x, camera.position.y, camera.position.z);
      } else {
        // The AABB can contain large areas where the photo has no recovered
        // triangles. Do not let horizontal movement enter those areas and
        // expose the generated gray ground; return to the last ray-validated
        // x/z position while preserving vertical flight at that position.
        const movedOutsideSurface =
          Math.abs(camera.position.x - lastValidTerrainPosition.current.x) > 1e-4 ||
          Math.abs(camera.position.z - lastValidTerrainPosition.current.z) > 1e-4;
        if (movedOutsideSurface) {
          camera.position.x = lastValidTerrainPosition.current.x;
          camera.position.z = lastValidTerrainPosition.current.z;
        }
      }
    }
    camera.rotation.set(lookRef.current.pitch, lookRef.current.yaw, 0, "YXZ");
    if (now - lastPositionReport.current > 200) {
      lastPositionReport.current = now;
      onPosition([camera.position.x, camera.position.y, camera.position.z]);
    }
  });
  return <primitive object={scene} />;
}

function SubjectViewer({ preview, actions = [], regions = [] }: { preview: string; actions?: Action[]; regions?: SubjectRegion[] }) {
  const [playing, setPlaying] = useState<Action>();
  const [message, setMessage] = useState("先观察原图；只有通过验收的动作素材才会播放。");
  const timer = useRef<number>();
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);
  function trigger(action: Action) {
    if (action.status !== "available" || !action.asset_url) {
      setMessage("这个动作素材尚未通过验收，已保留原图，不用静态抖动冒充回应。");
      return;
    }
    if (playing) return;
    setPlaying(action);
    setMessage(action.hint || "动作播放中");
    timer.current = window.setTimeout(() => { setPlaying(undefined); setMessage("回到待机状态，可以再次尝试。"); }, action.cooldown_ms);
  }
  return <div className="subject-viewer">
    <img src={preview} alt="主体原图" />
    {regions.map((region) => region.x != null && region.y != null && region.width != null && region.height != null ? <span key={region.region_id} className="subject-region" style={{ left: `${region.x * 100}%`, top: `${region.y * 100}%`, width: `${region.width * 100}%`, height: `${region.height * 100}%` }} title={region.label} /> : null)}
    {playing?.asset_url && <video className="subject-action-video" src={playing.asset_url} autoPlay muted playsInline onEnded={() => setPlaying(undefined)} />}
    <div className="subject-controls"><p>{message}</p>{actions.length ? actions.map((action) => <button key={action.action_id} onClick={() => trigger(action)} disabled={Boolean(playing)}>{action.label}{action.status !== "available" ? "（素材待验收）" : ""}</button>) : <span className="muted">当前没有可执行动作。</span>}</div>
  </div>;
}

function SceneViewer({ objectUrl, manifest }: { objectUrl: string; manifest: Manifest }) {
  const [dragging, setDragging] = useState(false);
  const [look, setLook] = useState({ yaw: 0, pitch: 0 });
  const [position, setPosition] = useState(manifest.movement.start);
  const last = useRef({ x: 0, y: 0 });
  const lookRef = useRef({ yaw: 0, pitch: 0 });
  const resetLook = useCallback(() => setLook({ yaw: 0, pitch: 0 }), []);
  const reportPosition = useCallback((next: number[]) => setPosition(next), []);
  useEffect(() => setPosition(manifest.movement.start), [manifest.scene_id, manifest.movement.start]);
  const move = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    const next = { yaw: lookRef.current.yaw - (event.clientX - last.current.x) * 0.005, pitch: THREE.MathUtils.clamp(lookRef.current.pitch - (event.clientY - last.current.y) * 0.005, -1.35, 1.35) };
    last.current = { x: event.clientX, y: event.clientY }; lookRef.current = next; setLook(next);
  };
  const cameraSpec = manifest.camera;
  const initialCamera = cameraSpec ?? { position: manifest.movement.start, fov_y: 68, near: 0.01, far: 200 };
  const debug = new URLSearchParams(window.location.search).get("debug") === "1";
  return <div className="scene-viewer" onPointerDown={(event) => { setDragging(true); last.current = { x: event.clientX, y: event.clientY }; (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId); }} onPointerUp={() => setDragging(false)} onPointerLeave={() => setDragging(false)} onPointerMove={move}>
    <Canvas camera={{ position: initialCamera.position as [number, number, number], fov: initialCamera.fov_y, near: initialCamera.near, far: initialCamera.far }} onCreated={({ scene }) => { scene.fog = cameraSpec ? null : new THREE.Fog("#15152b", 8, 40); }}>
      <color attach="background" args={["#15152b"]} /><ambientLight intensity={1.6} /><directionalLight position={[4, 8, 4]} intensity={1.2} />
      <Suspense fallback={null}><SceneContent objectUrl={objectUrl} manifest={manifest} lookRef={lookRef} onReset={resetLook} onPosition={reportPosition} /></Suspense>
    </Canvas>
    <div className="viewer-help">拖动360°环顾 · WASD移动 · R回到起点 · F飞行{manifest.movement.allow_flight ? " · 空格上升 · C下降" : ""}</div>
    <div className="viewer-tag">{manifest.template} · {manifest.engine ?? "legacy"} · {manifest.version}</div>
    {debug && <div className="viewer-debug">位置 {position.map((value) => value.toFixed(2)).join(" / ")} · {cameraSpec ? `FOV ${cameraSpec.fov_x?.toFixed(1)}°/${cameraSpec.fov_y?.toFixed(1)}° · scale ${cameraSpec.world_scale.toFixed(4)}` : "旧场景协议"}</div>}
    <span className="sr-only">视角 {look.yaw.toFixed(2)} / {look.pitch.toFixed(2)} · 位置 {position.map((value) => value.toFixed(2)).join(" / ")}</span>
  </div>;
}

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string>();
  const [plan, setPlan] = useState<Plan>();
  const [job, setJob] = useState<Job>();
  const [manifest, setManifest] = useState<Manifest>();
  const [sceneObjectUrl, setSceneObjectUrl] = useState<string>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<Job["generation_mode"]>("progressive");
  const [template, setTemplate] = useState<Template>();

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  useEffect(() => {
    if (!job?.scene_id) { setSceneObjectUrl(undefined); setManifest(undefined); return; }
    const id = job.scene_id;
    setSceneObjectUrl(apiUrl(`/api/scenes/${id}/scene.glb`));
    api(`/api/scenes/${id}/manifest`).then(setManifest).catch((e) => setError(e.message));
  }, [job?.scene_id]);
  useEffect(() => {
    if (!job?.job_id || job.state === "FULL_READY" || job.state === "FAILED" || job.state === "INTERRUPTED" || job.generation_mode === "quick" && job.state === "QUICK_READY") return;
    const timer = window.setInterval(async () => { try { setJob(await api(`/api/jobs/${job.job_id}`)); } catch { /* keep last state */ } }, 1000);
    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.state, job?.generation_mode]);

  const statusLabel = useMemo(() => {
    if (!job) return "等待确认";
    return job.message || job.state;
  }, [job]);

  function choose(next: File | null) {
    if (preview) URL.revokeObjectURL(preview);
    setFile(next); setPlan(undefined); setJob(undefined); setManifest(undefined); setError("");
    if (next) setPreview(URL.createObjectURL(next)); else setPreview(undefined);
  }
  async function analyze() {
    if (!file) return;
    setBusy(true); setError("");
    const form = new FormData(); form.append("file", file);
    try { const next = await api("/api/analyze", { method: "POST", body: form }); setPlan(next); setTemplate(next.recommended_template); }
    catch (e) { setError(e instanceof Error ? e.message : "分析失败"); } finally { setBusy(false); }
  }
  async function generate() {
    if (!plan) return;
    setBusy(true); setError("");
    try {
      const created = await api("/api/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ analysis_id: plan.analysis_id, selected_template: template || plan.recommended_template, generation_mode: mode }) });
      setJob(created);
    } catch (e) { setError(e instanceof Error ? e.message : "生成失败"); } finally { setBusy(false); }
  }
  async function retry() {
    if (!job) return;
    setBusy(true); setError("");
    try { setJob(await api(`/api/jobs/${job.job_id}/retry`, { method: "POST" })); }
    catch (e) { setError(e instanceof Error ? e.message : "重试失败"); }
    finally { setBusy(false); }
  }

  return <main className="shell"><header><div><p className="eyebrow">WALK INTO PHOTOS · LUNA MVP</p><h1>把照片变成一段可以走进去的体验</h1><p className="sub">拖入一张照片，AI先判断适合的入画方式；你确认模板和质量模式后，再开始本地生成。</p></div><span className="badge">八类模板 · 本地优先</span></header>
    <section className="grid">
      <div className="card upload"><h2>01 · 上传照片</h2><label className="drop" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); choose(e.dataTransfer.files?.[0] ?? null); }}>{preview ? <img src={preview} alt="待分析照片" /> : <><strong>拖入照片，或点击选择</strong><span>支持 JPEG / PNG / WebP，最大10MB</span></>}<input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => choose(e.target.files?.[0] ?? null)} /></label>{file && !plan && <button disabled={busy} onClick={analyze}>{busy ? "本地AI正在分析…" : "让AI判断这张照片"}</button>}</div>
      <div className="card plan"><h2>02 · AI规划与确认</h2>{plan ? <><span className="pill">{plan.experimental ? "通用实验模式" : plan.experience_kind === "interactive_subject" ? "主体互动候选" : "场景体验候选"}</span><h3>{plan.title}</h3><p>{plan.summary}</p><p className="reason">{plan.rationale}</p>{plan.actions?.length ? <div className="capability-box"><strong>建议操作</strong>{plan.actions.map((action) => <p key={action.action_id}>· {action.label}：{action.hint || "动作素材待验收"}</p>)}</div> : null}{plan.capability_notes?.map((note) => <p className="muted" key={note}>{note}</p>)}<label className="field">体验模板<select value={template || plan.recommended_template} onChange={(e) => setTemplate(e.target.value)}>{plan.compatible_templates.map((item) => <option key={item} value={item}>{item === plan.recommended_template ? `推荐 · ${item}` : item}</option>)}</select></label><div className="mode-grid">{(["quick", "full", "progressive"] as const).map((item) => <button key={item} className={mode === item ? "mode selected" : "mode"} onClick={() => setMode(item)}>{item === "quick" ? "快速体验" : item === "full" ? "完整体验" : "渐进体验（推荐）"}<small>{item === "quick" ? "目标3–5分钟，实际以设备计时为准" : item === "full" ? "目标≥10分钟，实际以设备计时为准" : "先玩快速版，再后台升级"}</small></button>)}</div><ul>{plan.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul><div className="actions"><button disabled={busy} onClick={generate}>{busy ? "正在进入队列…" : "确认生成"}</button><button className="ghost" onClick={() => choose(null)}>更换照片</button></div></> : <p className="muted">上传后，本地AI会给出首选模板和可兼容的替代方案。</p>}</div>
    </section>
    {job && <section className="card result"><div><h2>03 · 体验与交付</h2><p>{statusLabel} · 阶段 {job.progress}%</p>{job.stage_timings_ms && Object.keys(job.stage_timings_ms).length ? <p className="muted">实际生成耗时：{Object.entries(job.stage_timings_ms).map(([stage, ms]) => `${stage} ${(ms / 1000).toFixed(1)}秒`).join(" · ")}</p> : null}{job.validation_status !== "passed" && <p className="notice">质量验收：{job.validation_status === "failed" ? "未通过" : job.validation_status === "needs_review" ? "待复核" : "尚未验收"}。生成完成不等于质量通过。</p>}{job.state === "INTERRUPTED" && <p className="notice">任务因进程重启而中断；当前未提供断点续算，请保留这条记录并重新确认生成。</p>}{job.state === "QUICK_READY" && job.generation_mode === "progressive" && <p className="notice">快速版已经可以玩，完整版正在后台顺序生成。</p>}{job.state === "FULL_READY" && <p className="notice">完整版候选已完成；细节改善仍需对比质检，不能仅凭分辨率宣称完成。</p>}{manifest && <p className="notice">{manifest.generated_region_note}</p>}{manifest && <p className="muted">机器检查：{manifest.quality_status === "failed" ? "失败" : manifest.quality_status === "needs_visual_review" ? "通过基础结构检查，仍需视觉复核" : "未完成"}。{manifest.coverage == null ? "几何覆盖率未测量。" : `可见覆盖率 ${(manifest.coverage * 100).toFixed(1)}%。`}</p>}</div><div className="progress"><span style={{ width: `${job.progress}%` }} /></div>{job.scene_id && sceneObjectUrl && manifest && (manifest.experience_kind === "interactive_subject" && preview ? <SubjectViewer preview={preview} actions={manifest.actions} regions={manifest.subject_regions} /> : !manifest.mock && !manifest.camera ? <p className="notice">这是旧版本真实场景，没有新版相机协议，已停止展示。请重新上传照片并生成新版场景。</p> : <SceneViewer objectUrl={sceneObjectUrl} manifest={manifest} />)}<div className="actions">{job.state === "FAILED" || job.state === "INTERRUPTED" ? <button onClick={retry} disabled={busy}>重新生成</button> : null}{job.scene_id && <a className="button" href={apiUrl(`/api/scenes/${job.scene_id}/scene.glb`)} download>下载 GLB</a>}{job.scene_id && <a className="button" href={apiUrl(`/api/scenes/${job.scene_id}/export`)} download>导出当前包</a>}</div></section>}
    {error && <p className="error global">{error}</p>}<footer>照片只在本机处理；不可见区域会标注为AI创作，不宣称真实空间复原。当前单GPU队列一次只运行一个模型任务。</footer></main>;
}
