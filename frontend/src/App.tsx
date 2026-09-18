import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import * as THREE from "three";
import { directionForYaw, resolveHorizontalMovement } from "./movement";

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
type RegionConfirmation = { region_id: string; role: "floor" | "wall" | "obstacle"; label: string; x: number; y: number; width: number; height: number };
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
  quality_route?: boolean;
  quick_scene_id?: string;
  full_scene_id?: string;
  scene_id?: string;
  error?: string;
  validation_status?: "not_run" | "passed" | "failed" | "needs_review";
  quality_status?: "unverified" | "needs_visual_review" | "failed" | string;
  stage_timings_ms?: Record<string, number>;
};
type Movement = { kind: string; start: number[]; bounds: Record<string, number[]>; walk_speed: number; fly_speed: number; allow_flight: boolean; ground_follow?: boolean; ground_y?: number; collision_radius?: number; collision_boxes?: { box_id: string; bounds: { x?: number[]; z?: number[] }; label?: string }[]; route_checkpoints?: number[][] };
type CameraSpec = { position: number[]; intrinsics?: number[][]; image_size?: number[]; camera_to_world?: number[][]; world_scale: number; near: number; far: number; fov_x?: number; fov_y?: number; coordinate_frame_id: string };
type Manifest = { scene_id: string; scene_url: string; export_url: string; version: string; template: Template; engine?: string; movement: Movement; camera?: CameraSpec; source_url?: string; generated_region_note: string; mock: boolean; experience_kind?: ExperienceKind; actions?: Action[]; subject_regions?: SubjectRegion[]; capability_status?: Action["status"]; coverage?: number | null; quality_status?: string; quality_metrics?: Record<string, unknown>; input_sha256?: string; provider_version?: string; coordinate_frame_id?: string; resource_manifest?: string[]; collision_resource?: string; acceptance_evidence?: string[]; generation_source?: string; fallback_reason?: string; layout_version?: string; estimated_scale?: number; quality_route?: boolean; manual_assisted?: boolean; manual_region_sha256?: string; photo_supported_regions?: string[]; generated_regions?: string[]; pixel_spec?: { lighting_preset?: string; [key: string]: unknown } };
type RouteInputEvent = { at_ms: number; type: "keydown" | "keyup" | "blur" | "visibilitychange" | "reset"; key?: string; position: number[]; yaw: number; pitch: number; keys: string[] };
type RouteFrameSample = { at_ms: number; delta_ms: number; position: number[]; yaw: number; pitch: number; keys: string[] };

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");
const apiUrl = (path: string) => path.startsWith("http://") || path.startsWith("https://") ? path : `${API_BASE_URL}${path}`;

const api = async (url: string, init?: RequestInit) => {
  const response = await fetch(apiUrl(url), { credentials: "include", ...init });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail ?? "请求失败");
  return body;
};

function lightingFor(manifest: Manifest) {
  const preset = manifest.pixel_spec?.lighting_preset;
  const presets: Record<string, { background: string; sky: string; ground: string; hemi: number; ambient: number; key: string; keyIntensity: number; fill: string; fillIntensity: number; shadows: boolean; emissiveLift: number }> = {
    indoor_warm_window: { background: "#293044", sky: "#fff3da", ground: "#4d5262", hemi: 0.92, ambient: 0.58, key: "#ffd39a", keyIntensity: 1.55, fill: "#9ab8db", fillIntensity: 0.28, shadows: true, emissiveLift: 0.018 },
    indoor_warm_window_v2: { background: "#252b3d", sky: "#fff0d0", ground: "#454858", hemi: 0.70, ambient: 0.36, key: "#ffd09a", keyIntensity: 1.82, fill: "#9bb8d8", fillIntensity: 0.16, shadows: true, emissiveLift: 0.006 },
    indoor_pixel_cozy_v3: { background: "#20283a", sky: "#fff1d6", ground: "#383d4a", hemi: 0.48, ambient: 0.22, key: "#ffd09a", keyIntensity: 2.18, fill: "#7999bd", fillIntensity: 0.08, shadows: true, emissiveLift: 0.004 },
    indoor_pixel_detail_v4: { background: "#1b2437", sky: "#ffe8bd", ground: "#353a48", hemi: 0.58, ambient: 0.28, key: "#ffd39b", keyIntensity: 2.02, fill: "#86a9c9", fillIntensity: 0.14, shadows: true, emissiveLift: 0.008 },
    outdoor_cool_daylight: { background: "#7694aa", sky: "#d9efff", ground: "#6d7d87", hemi: 1.25, ambient: 0.68, key: "#e8f5ff", keyIntensity: 1.45, fill: "#9fc6e6", fillIntensity: 0.18, shadows: true, emissiveLift: 0.008 },
    outdoor_cool_daylight_v2: { background: "#647f98", sky: "#e7f4ff", ground: "#526b7d", hemi: 0.84, ambient: 0.34, key: "#f4fbff", keyIntensity: 1.78, fill: "#86acd1", fillIntensity: 0.10, shadows: true, emissiveLift: 0.004 },
    street_soft_daylight: { background: "#273244", sky: "#e4eef3", ground: "#626c70", hemi: 1.10, ambient: 0.66, key: "#fff2d5", keyIntensity: 1.30, fill: "#9fc5dc", fillIntensity: 0.24, shadows: true, emissiveLift: 0.012 },
    street_soft_daylight_v2: { background: "#202c40", sky: "#e8f3f7", ground: "#58636a", hemi: 0.76, ambient: 0.40, key: "#fff0d2", keyIntensity: 1.62, fill: "#8fb5d0", fillIntensity: 0.14, shadows: true, emissiveLift: 0.006 },
    facade_blue_hour: { background: "#18243a", sky: "#b4cced", ground: "#34394d", hemi: 0.78, ambient: 0.42, key: "#b6d5ff", keyIntensity: 0.92, fill: "#f3b26c", fillIntensity: 0.32, shadows: true, emissiveLift: 0.012 },
    facade_blue_hour_v2: { background: "#142039", sky: "#c0d9f2", ground: "#2c354c", hemi: 0.62, ambient: 0.28, key: "#c4ddff", keyIntensity: 1.10, fill: "#f6ad68", fillIntensity: 0.46, shadows: true, emissiveLift: 0.016 },
    facade_blue_hour_v3: { background: "#101b34", sky: "#c8e0f7", ground: "#26334b", hemi: 0.82, ambient: 0.40, key: "#c0ddff", keyIntensity: 1.28, fill: "#ffb870", fillIntensity: 0.58, shadows: true, emissiveLift: 0.028 },
    street_soft_daylight_v3: { background: "#1f2d42", sky: "#eaf6fb", ground: "#4f5f68", hemi: 0.92, ambient: 0.48, key: "#fff3da", keyIntensity: 1.76, fill: "#9bc7dc", fillIntensity: 0.20, shadows: true, emissiveLift: 0.010 },
  };
  return presets[preset ?? ""] ?? { background: "#263044", sky: "#f8fbff", ground: "#7d8798", hemi: 1.2, ambient: 1.0, key: "#ffffff", keyIntensity: 1.2, fill: "#ffffff", fillIntensity: 0, shadows: false, emissiveLift: 0.07 };
}

function SceneContent({ objectUrl, manifest, lookRef, onReset, onPosition, onInputEvent, onFrameSample, active }: { objectUrl: string; manifest: Manifest; lookRef: React.MutableRefObject<{ yaw: number; pitch: number }>; onReset: () => void; onPosition: (position: number[]) => void; onInputEvent: (event: RouteInputEvent) => void; onFrameSample: (sample: RouteFrameSample) => void; active: boolean }) {
  const { scene } = useGLTF(objectUrl);
  const { camera, size, gl } = useThree();
  const lighting = lightingFor(manifest);
  const keys = useRef(new Set<string>());
  const flying = useRef(false);
  const lastPositionReport = useRef(0);
  const lastTerrainCollisionCheck = useRef(0);
  const lastValidTerrainPosition = useRef(new THREE.Vector3());
  const movement = manifest.movement;
  const emitInputEvent = (type: RouteInputEvent["type"], key?: string) => onInputEvent({
    at_ms: performance.now(),
    type,
    key,
    position: [camera.position.x, camera.position.y, camera.position.z],
    yaw: lookRef.current.yaw,
    pitch: lookRef.current.pitch,
    keys: Array.from(keys.current).sort(),
  });
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
    gl.shadowMap.enabled = lighting.shadows;
    gl.shadowMap.type = THREE.PCFSoftShadowMap;
    scene.traverse((object) => {
      const mesh = object as THREE.Mesh;
      const material = mesh.material;
      if (mesh.isMesh) { mesh.castShadow = lighting.shadows; mesh.receiveShadow = lighting.shadows; }
      if (!material) return;
      const materials = Array.isArray(material) ? material : [material];
      for (const entry of materials) {
        entry.side = THREE.DoubleSide;
        // Coarse GLBs are intentionally low-detail and can contain interior
        // faces whose normal receives little direct light. A small emissive
        // lift keeps the room readable without changing geometry or colour
        // provenance.
        if ("emissive" in entry && "color" in entry) {
          const lit = entry as THREE.MeshStandardMaterial;
          lit.emissive.copy(lit.color);
          lit.emissiveIntensity = lighting.emissiveLift;
        }
        entry.needsUpdate = true;
      }
    });
  }, [gl, lighting.emissiveLift, lighting.shadows, scene]);
  useEffect(() => {
    const clearKeys = (eventType: "blur" | "visibilitychange" = "blur") => {
      keys.current.clear();
      emitInputEvent(eventType);
    };
    if (!active) { clearKeys(); return; }
    const down = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      // These keys belong to the scene controller. In particular, Space has
      // a browser-level default action (scroll the document) which otherwise
      // runs at the same time as the flight controller moves the camera.
      const sceneKeys = new Set([" ", "w", "a", "s", "d", "c", "f", "r", "arrowup", "arrowdown", "arrowleft", "arrowright"]);
      if (sceneKeys.has(key)) event.preventDefault();
      if (key === "f" && event.repeat) return;
      keys.current.add(key);
      emitInputEvent("keydown", key);
      if (key === "f" && movement.allow_flight) flying.current = !flying.current;
      if (key === "r") {
        flying.current = false;
        camera.position.set(...(movement.start as [number, number, number]));
        lookRef.current = { yaw: 0, pitch: 0 };
        emitInputEvent("reset", key);
        onReset();
      }
    };
    const up = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      if (key === " ") event.preventDefault();
      keys.current.delete(key);
      emitInputEvent("keyup", key);
    };
    const onWindowBlur = () => clearKeys("blur");
    const onVisibilityChange = () => clearKeys("visibilitychange");
    window.addEventListener("keydown", down, { passive: false }); window.addEventListener("keyup", up, { passive: false });
    window.addEventListener("blur", onWindowBlur); document.addEventListener("visibilitychange", onVisibilityChange);
    // Keep the user's position when a progressive full scene swaps in. A new
    // SceneContent instance still starts at the manifest origin.
    if (camera.userData.walkIntoPhotosInitialized !== true) {
      camera.position.set(...(movement.start as [number, number, number]));
      camera.userData.walkIntoPhotosInitialized = true;
    }
    lastValidTerrainPosition.current.set(camera.position.x, camera.position.y, camera.position.z);
    if (manifest.camera && camera instanceof THREE.PerspectiveCamera) {
      const spec = manifest.camera;
      const canvasAspect = Math.max(size.width / Math.max(size.height, 1), 0.1);
      const imageAspect = spec.image_size && spec.image_size[1] ? spec.image_size[0] / spec.image_size[1] : canvasAspect;
      // MoGe's fov_x/fov_y belongs to the source image aspect. R3F changes
      // camera.aspect to the viewer canvas, so applying fov_y unchanged on a
      // wide canvas expands the horizontal view and leaves the photo surface
      // squeezed into the centre. Preserve the source framing by deriving the
      // other angle from the wider side of the actual canvas.
      if (spec.fov_x != null && spec.fov_y != null) {
        const radians = (degrees: number) => degrees * Math.PI / 180;
        const degrees = (radiansValue: number) => radiansValue * 180 / Math.PI;
        camera.fov = canvasAspect >= imageAspect
          ? degrees(2 * Math.atan(Math.tan(radians(spec.fov_x) / 2) / canvasAspect))
          : spec.fov_y;
      } else {
        camera.fov = spec.fov_y ?? camera.fov;
      }
      camera.aspect = canvasAspect;
      camera.near = manifest.camera.near;
      camera.far = manifest.camera.far;
      camera.updateProjectionMatrix();
    }
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); window.removeEventListener("blur", onWindowBlur); document.removeEventListener("visibilitychange", onVisibilityChange); };
  }, [active, camera, manifest.camera, movement, onInputEvent, onReset, size.height, size.width]);
  useFrame((_, delta) => {
    const forward = Number(keys.current.has("w") || keys.current.has("arrowup")) - Number(keys.current.has("s") || keys.current.has("arrowdown"));
    const sideways = Number(keys.current.has("d") || keys.current.has("arrowright")) - Number(keys.current.has("a") || keys.current.has("arrowleft"));
    const directionLength = Math.hypot(forward, sideways) || 1;
    const frameDelta = Math.min(Math.max(delta, 0), 0.05);
    const speed = (flying.current ? movement.fly_speed : movement.walk_speed) * frameDelta;
    const yaw = lookRef.current.yaw;
    const direction = directionForYaw(yaw, forward / directionLength, sideways / directionLength);
    const resolved = resolveHorizontalMovement(
      [camera.position.x, camera.position.y, camera.position.z],
      { x: direction.x * speed, z: direction.z * speed },
      movement,
    );
    camera.position.x = resolved[0];
    camera.position.z = resolved[2];
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
    onFrameSample({
      at_ms: now,
      delta_ms: delta * 1000,
      position: [camera.position.x, camera.position.y, camera.position.z],
      yaw: lookRef.current.yaw,
      pitch: lookRef.current.pitch,
      keys: Array.from(keys.current).sort(),
    });
  });
  return <primitive object={scene} />;
}

function SubjectViewer({ preview, actions = [], regions = [] }: { preview: string; actions?: Action[]; regions?: SubjectRegion[] }) {
  type Playback = { action: Action; state: "playing" | "cooldown" };
  type SubjectPoint = { x: number; y: number };
  const [playback, setPlayback] = useState<Playback>();
  const [message, setMessage] = useState("先观察原图；只有通过验收的动作素材才会播放。");
  const [imageBox, setImageBox] = useState({ left: 0, top: 0, width: 0, height: 0 });
  const containerRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const cooldownTimer = useRef<number>();
  const drag = useRef<{ action?: Action; start: SubjectPoint; last: SubjectPoint; moved: boolean }>();
  const activeAction = playback?.action;
  const activeRegion = (action: Action) => action.target_region_id ? regions.find((region) => region.region_id === action.target_region_id) : undefined;

  const updateImageBox = useCallback(() => {
    const image = imageRef.current;
    const container = containerRef.current;
    if (!image || !container || !image.naturalWidth || !image.naturalHeight) return;
    const imageRect = image.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    const scale = Math.min(imageRect.width / image.naturalWidth, imageRect.height / image.naturalHeight);
    const width = image.naturalWidth * scale;
    const height = image.naturalHeight * scale;
    setImageBox({ left: imageRect.left - containerRect.left + (imageRect.width - width) / 2, top: imageRect.top - containerRect.top + (imageRect.height - height) / 2, width, height });
  }, []);

  useEffect(() => {
    const update = () => window.requestAnimationFrame(updateImageBox);
    window.addEventListener("resize", update);
    update();
    return () => window.removeEventListener("resize", update);
  }, [preview, updateImageBox]);

  useEffect(() => () => { if (cooldownTimer.current) window.clearTimeout(cooldownTimer.current); }, []);

  function pointFromEvent(event: React.PointerEvent): SubjectPoint | undefined {
    const image = imageRef.current;
    if (!image || !image.naturalWidth || !image.naturalHeight) return undefined;
    const rect = image.getBoundingClientRect();
    const scale = Math.min(rect.width / image.naturalWidth, rect.height / image.naturalHeight);
    const width = image.naturalWidth * scale;
    const height = image.naturalHeight * scale;
    const left = rect.left + (rect.width - width) / 2;
    const top = rect.top + (rect.height - height) / 2;
    const point = { x: (event.clientX - left) / width, y: (event.clientY - top) / height };
    return point.x >= 0 && point.x <= 1 && point.y >= 0 && point.y <= 1 ? point : undefined;
  }

  function inside(point: SubjectPoint | undefined, region: SubjectRegion | undefined) {
    return Boolean(point && region?.x != null && region.y != null && region.width != null && region.height != null && point.x >= region.x && point.x <= region.x + region.width && point.y >= region.y && point.y <= region.y + region.height);
  }

  function finishPlayback(action: Action, nextMessage: string) {
    if (playback?.action.action_id !== action.action_id || playback.state !== "playing") return;
    setPlayback({ action, state: "cooldown" });
    setMessage(nextMessage);
    if (cooldownTimer.current) window.clearTimeout(cooldownTimer.current);
    cooldownTimer.current = window.setTimeout(() => { setPlayback(undefined); setMessage("回到待机状态，可以再次尝试。"); }, Math.max(0, action.cooldown_ms));
  }

  function playbackError(action: Action) {
    finishPlayback(action, "动作播放失败，已保留原图；可以稍后再次尝试。");
  }

  function trigger(action: Action) {
    if (action.status !== "available" || !action.asset_url) {
      setMessage("这个动作素材尚未通过验收，已保留原图，不用静态抖动冒充回应。");
      return;
    }
    if (playback) return;
    setPlayback({ action, state: "playing" });
    setMessage(action.hint || "动作播放中");
  }

  function onPointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (playback) return;
    const point = pointFromEvent(event);
    const action = actions.find((candidate) => candidate.trigger === "mouse_stroke" && candidate.status === "available" && Boolean(candidate.asset_url) && inside(point, activeRegion(candidate)));
    drag.current = point ? { action, start: point, last: point, moved: false } : undefined;
    if (point) { containerRef.current?.setPointerCapture(event.pointerId); }
  }

  function onPointerMove(event: React.PointerEvent<HTMLDivElement>) {
    if (!drag.current) return;
    const point = pointFromEvent(event);
    if (!point) return;
    drag.current.moved = drag.current.moved || Math.hypot(point.x - drag.current.start.x, point.y - drag.current.start.y) >= 0.025;
    drag.current.last = point;
  }

  function onPointerUp(event: React.PointerEvent<HTMLDivElement>) {
    const current = drag.current;
    drag.current = undefined;
    if (!current?.action || !current.moved || !inside(current.last, activeRegion(current.action))) return;
    trigger(current.action);
    containerRef.current?.releasePointerCapture(event.pointerId);
  }

  return <div ref={containerRef} className="subject-viewer" onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={() => { drag.current = undefined; }}>
    <img ref={imageRef} src={preview} alt="主体原图" onLoad={updateImageBox} />
    {regions.map((region) => region.x != null && region.y != null && region.width != null && region.height != null && imageBox.width ? <span key={region.region_id} className="subject-region" style={{ left: `${imageBox.left + region.x * imageBox.width}px`, top: `${imageBox.top + region.y * imageBox.height}px`, width: `${region.width * imageBox.width}px`, height: `${region.height * imageBox.height}px` }} title={region.label} /> : null)}
    {activeAction?.asset_url && playback?.state === "playing" && <video className="subject-action-video" style={{ left: `${imageBox.left}px`, top: `${imageBox.top}px`, width: `${imageBox.width}px`, height: `${imageBox.height}px` }} src={activeAction.asset_url} autoPlay muted playsInline onCanPlay={(event) => { event.currentTarget.play().catch(() => playbackError(activeAction)); }} onEnded={() => finishPlayback(activeAction, "动作播放结束，正在冷却。")} onError={() => playbackError(activeAction)} />}
    <div className="subject-controls"><p>{message}</p>{actions.length ? actions.map((action) => action.trigger === "mouse_stroke" ? <span className="action-hint" key={action.action_id}>{action.label}：在目标框内拖动{action.status !== "available" ? "（素材待验收）" : ""}</span> : <button key={action.action_id} onClick={() => trigger(action)} disabled={Boolean(playback)}>{action.label}{action.status !== "available" ? "（素材待验收）" : ""}</button>) : <span className="muted">当前没有可执行动作。</span>}</div>
  </div>;
}

function SceneViewer({ objectUrl, manifest }: { objectUrl: string; manifest: Manifest }) {
  const viewerRef = useRef<HTMLDivElement>(null);
  const [focused, setFocused] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [look, setLook] = useState({ yaw: 0, pitch: 0 });
  const [position, setPosition] = useState(manifest.movement.start);
  const [recording, setRecording] = useState(false);
  const [recordingElapsed, setRecordingElapsed] = useState(0);
  const [recorderMessage, setRecorderMessage] = useState("");
  const [routeUrl, setRouteUrl] = useState<string>();
  const [videoUrl, setVideoUrl] = useState<string>();
  const last = useRef({ x: 0, y: 0 });
  const lookRef = useRef({ yaw: 0, pitch: 0 });
  const canvasRef = useRef<HTMLCanvasElement>();
  const recorderRef = useRef<MediaRecorder>();
  const streamRef = useRef<MediaStream>();
  const recordingRef = useRef(false);
  const timerRef = useRef<number>();
  const routeRef = useRef<{ startedAt: number; events: RouteInputEvent[]; frames: RouteFrameSample[] }>();
  const resetLook = useCallback(() => setLook({ yaw: 0, pitch: 0 }), []);
  const reportPosition = useCallback((next: number[]) => setPosition(next), []);
  const recordInputEvent = useCallback((event: RouteInputEvent) => {
    if (!recordingRef.current || !routeRef.current) return;
    routeRef.current.events.push({ ...event, at_ms: Number((event.at_ms - routeRef.current.startedAt).toFixed(3)) });
  }, []);
  const recordFrameSample = useCallback((sample: RouteFrameSample) => {
    if (!recordingRef.current || !routeRef.current) return;
    routeRef.current.frames.push({ ...sample, at_ms: Number((sample.at_ms - routeRef.current.startedAt).toFixed(3)) });
  }, []);
  const setCanvas = useCallback((canvas: HTMLCanvasElement) => { canvasRef.current = canvas; }, []);
  useEffect(() => setPosition(manifest.movement.start), [manifest.scene_id, manifest.movement.start]);
  useEffect(() => () => {
    recordingRef.current = false;
    if (recorderRef.current && recorderRef.current.state !== "inactive") recorderRef.current.stop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    if (routeUrl) URL.revokeObjectURL(routeUrl);
    if (videoUrl) URL.revokeObjectURL(videoUrl);
    if (timerRef.current) window.clearInterval(timerRef.current);
  }, [routeUrl, videoUrl]);

  function percentile(values: number[], fraction: number) {
    if (!values.length) return null;
    const sorted = [...values].sort((a, b) => a - b);
    return sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * fraction))];
  }

  function stopRecording() {
    recordingRef.current = false;
    setRecording(false);
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = undefined;
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    recorderRef.current = undefined;
    streamRef.current = undefined;
    setRecorderMessage("正在整理路线和录像…");
  }

  function startRecording() {
    const canvas = canvasRef.current;
    if (!canvas || typeof canvas.captureStream !== "function" || typeof MediaRecorder === "undefined") {
      setRecorderMessage("当前浏览器不支持画布录像；仍可用手动长按验收。未生成录像文件。");
      return;
    }
    if (routeUrl) URL.revokeObjectURL(routeUrl);
    if (videoUrl) URL.revokeObjectURL(videoUrl);
    setRouteUrl(undefined); setVideoUrl(undefined); setRecorderMessage("");
    const startedAt = performance.now();
    routeRef.current = { startedAt, events: [], frames: [] };
    const stream = canvas.captureStream(30);
    const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9")
      ? "video/webm;codecs=vp9"
      : MediaRecorder.isTypeSupported("video/webm") ? "video/webm" : "";
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
    recorder.onstop = () => {
      const route = routeRef.current;
      if (!route) return;
      const deltas = route.frames.map((sample) => sample.delta_ms).filter((value) => Number.isFinite(value));
      const routePayload = {
        schema: "luna-route-evidence/1",
        scene_id: manifest.scene_id,
        scene_version: manifest.version,
        started_at: new Date().toISOString(),
        recording_fps_target: 30,
        events: route.events,
        frames: route.frames,
        metrics: {
          frame_count: deltas.length,
          duration_ms: route.frames.length ? route.frames[route.frames.length - 1].at_ms : 0,
          delta_ms_p50: percentile(deltas, 0.50),
          delta_ms_p95: percentile(deltas, 0.95),
          over_33_3ms: deltas.filter((value) => value > 33.3).length,
          over_100ms: deltas.filter((value) => value > 100).length,
        },
        notes: ["录像是画布连续帧；按键、位置和朝向来自同一运行时记录。需结合路线检查判定碰撞和失焦。"],
      };
      setRouteUrl(URL.createObjectURL(new Blob([JSON.stringify(routePayload, null, 2)], { type: "application/json" })));
      if (chunks.length) setVideoUrl(URL.createObjectURL(new Blob(chunks, { type: mimeType || "video/webm" })));
      setRecorderMessage(`已保存 ${route.frames.length} 帧、${route.events.length} 个输入事件。`);
    };
    recorderRef.current = recorder;
    streamRef.current = stream;
    recordingRef.current = true;
    setRecording(true); setRecordingElapsed(0);
    recorder.start(250);
    timerRef.current = window.setInterval(() => setRecordingElapsed(performance.now() - startedAt), 250);
  }
  const move = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    const next = { yaw: lookRef.current.yaw - (event.clientX - last.current.x) * 0.005, pitch: THREE.MathUtils.clamp(lookRef.current.pitch - (event.clientY - last.current.y) * 0.005, -1.35, 1.35) };
    last.current = { x: event.clientX, y: event.clientY }; lookRef.current = next; setLook(next);
  };
  const cameraSpec = manifest.camera;
  const initialCamera = cameraSpec ?? { position: manifest.movement.start, fov_y: 68, near: 0.01, far: 200 };
  const activeLighting = lightingFor(manifest);
  const debug = new URLSearchParams(window.location.search).get("debug") === "1";
  return <div ref={viewerRef} className="scene-viewer" tabIndex={0} onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} onPointerDown={(event) => { viewerRef.current?.focus(); setFocused(true); setDragging(true); last.current = { x: event.clientX, y: event.clientY }; (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId); }} onPointerUp={() => setDragging(false)} onPointerLeave={() => setDragging(false)} onPointerMove={move}>
    <Canvas camera={{ position: initialCamera.position as [number, number, number], fov: initialCamera.fov_y, near: initialCamera.near, far: initialCamera.far }} shadows={activeLighting.shadows} onCreated={({ gl, scene }) => { setCanvas(gl.domElement); gl.setClearColor(activeLighting.background, 1); scene.fog = cameraSpec ? null : new THREE.Fog("#15152b", 8, 40); }}>
      <color attach="background" args={[activeLighting.background]} /><hemisphereLight args={[activeLighting.sky, activeLighting.ground, activeLighting.hemi]} /><ambientLight color={activeLighting.sky} intensity={activeLighting.ambient} /><directionalLight color={activeLighting.key} position={[4, 8, 4]} intensity={activeLighting.keyIntensity} castShadow={activeLighting.shadows} shadow-mapSize-width={1024} shadow-mapSize-height={1024} shadow-camera-near={0.1} shadow-camera-far={80} shadow-camera-left={-24} shadow-camera-right={24} shadow-camera-top={24} shadow-camera-bottom={-24} shadow-bias={-0.0008} />{activeLighting.fillIntensity > 0 && <directionalLight color={activeLighting.fill} position={[-5, 3, -6]} intensity={activeLighting.fillIntensity} />}
      <Suspense fallback={null}><SceneContent objectUrl={objectUrl} manifest={manifest} lookRef={lookRef} onReset={resetLook} onPosition={reportPosition} onInputEvent={recordInputEvent} onFrameSample={recordFrameSample} active={focused} /></Suspense>
    </Canvas>
    <div className="viewer-help">拖动360°环顾 · WASD移动 · R回到起点 · F飞行{manifest.movement.allow_flight ? " · 空格上升 · C下降" : ""}</div>
    <div className="viewer-tag">{manifest.template} · {manifest.generation_source ?? manifest.engine ?? "legacy"} · {manifest.version}</div>
    <div className="viewer-recorder"><button className={recording ? "recording" : "ghost"} onClick={recording ? stopRecording : startRecording}>{recording ? `停止路线录制 ${(recordingElapsed / 1000).toFixed(1)}s` : "开始路线录制"}</button>{routeUrl && <a className="button" href={routeUrl} download={`${manifest.scene_id}-route.json`}>下载路线 JSON</a>}{videoUrl && <a className="button" href={videoUrl} download={`${manifest.scene_id}-route.webm`}>下载连续录像</a>}{recorderMessage && <span>{recorderMessage}</span>}</div>
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
  const [mode, setMode] = useState<Job["generation_mode"]>("quick");
  const [template, setTemplate] = useState<Template>();
  const [assistMode, setAssistMode] = useState(false);
  const [assistRole, setAssistRole] = useState<RegionConfirmation["role"]>("floor");
  const [assistRegions, setAssistRegions] = useState<RegionConfirmation[]>([]);

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  useEffect(() => {
    if (!job?.scene_id) { setSceneObjectUrl(undefined); setManifest(undefined); return; }
    const id = job.scene_id;
    setSceneObjectUrl(apiUrl(`/api/scenes/${id}/scene.glb`));
    setManifest(undefined);
    let cancelled = false;
    api(`/api/scenes/${id}/manifest`).then((next) => {
      if (!cancelled && next.scene_id === id) setManifest(next);
    }).catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [job?.scene_id]);
  useEffect(() => {
    if (!job?.job_id || job.state === "FULL_READY" || job.state === "FAILED" || job.state === "INTERRUPTED" || job.state === "CANCELLED" || job.state === "QUICK_READY" && (job.generation_mode === "quick" || Boolean(job.error))) return;
    const timer = window.setInterval(async () => { try { setJob(await api(`/api/jobs/${job.job_id}`)); } catch { /* keep last state */ } }, 1000);
    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.state, job?.generation_mode]);

  const statusLabel = useMemo(() => {
    if (!job) return "等待确认";
    return job.message || job.state;
  }, [job]);

  function choose(next: File | null) {
    if (preview) URL.revokeObjectURL(preview);
    setFile(next); setPlan(undefined); setJob(undefined); setManifest(undefined); setError(""); setAssistMode(false); setAssistRegions([]);
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
      const created = await api("/api/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ analysis_id: plan.analysis_id, selected_template: template || plan.recommended_template, generation_mode: mode, quality_route: true, region_confirmations: assistRegions }) });
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
  function markRegion(event: React.MouseEvent<HTMLImageElement>) {
    if (!assistMode) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = event.currentTarget.getBoundingClientRect();
    const width = 0.18;
    const height = 0.18;
    const centerX = (event.clientX - rect.left) / rect.width;
    const centerY = (event.clientY - rect.top) / rect.height;
    const x = Math.max(0, Math.min(1 - width, centerX - width / 2));
    const y = Math.max(0, Math.min(1 - height, centerY - height / 2));
    const index = assistRegions.length + 1;
    setAssistRegions((current) => [...current, { region_id: `user_region_${index}`, role: assistRole, label: assistRole === "floor" ? "用户确认地面" : assistRole === "wall" ? "用户确认墙面" : "用户确认障碍", x, y, width, height }]);
    setAssistMode(false);
  }
  async function cancel() {
    if (!job) return;
    setBusy(true); setError("");
    try { setJob(await api(`/api/jobs/${job.job_id}/cancel`, { method: "POST" })); }
    catch (e) { setError(e instanceof Error ? e.message : "取消失败"); }
    finally { setBusy(false); }
  }

  return <main className="shell"><header><div><p className="eyebrow">WALK INTO PHOTOS · LUNA MVP</p><h1>把照片变成一段可以走进去的体验</h1><p className="sub">拖入一张照片，AI先判断路线；确认后恢复照片表面并补齐可行走的简化结构。</p></div><span className="badge">照片支持质量路线 · 本地优先</span></header>
    <section className="grid">
      <div className="card upload"><h2>01 · 上传照片</h2><label className="drop" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); choose(e.dataTransfer.files?.[0] ?? null); }}>{preview ? <img className={assistMode ? "confirm-target" : ""} src={preview} alt="待分析照片" onClick={markRegion} /> : <><strong>拖入照片，或点击选择</strong><span>支持 JPEG / PNG / WebP，最大10MB</span></>}<input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => choose(e.target.files?.[0] ?? null)} /></label>{file && !plan && <button disabled={busy} onClick={analyze}>{busy ? "本地AI正在分析…" : "让AI判断这张照片"}</button>}{plan && <div className="assist-box"><p>可选区域确认：自动判断不可靠时，在照片上点一次确认地面、墙面或主要障碍；不确认也可直接生成。</p><div className="assist-row"><select value={assistRole} onChange={(e) => setAssistRole(e.target.value as RegionConfirmation["role"])}><option value="floor">地面</option><option value="wall">墙面／边界</option><option value="obstacle">主要障碍</option></select><button className="ghost" onClick={() => setAssistMode((current) => !current)}>{assistMode ? "请点击左侧照片" : "开始可选确认"}</button></div>{assistRegions.length ? <p className="muted-inline">已确认 {assistRegions.length} 个区域：{assistRegions.map((region) => region.label).join("、")}</p> : null}</div>}</div>
      <div className="card plan"><h2>02 · AI规划与确认</h2>{plan ? <><span className="pill">{plan.experimental ? "备用：通用展示空间" : plan.experience_kind === "interactive_subject" ? "主体照片 · 空间化展示" : "照片支持质量路线"}</span><h3>{plan.title}</h3><p>{plan.summary}</p><p className="reason">{plan.rationale}</p>{plan.actions?.length ? <div className="capability-box"><strong>建议操作</strong>{plan.actions.map((action) => <p key={action.action_id}>· {action.label}：{action.hint || "动作素材待验收"}</p>)}</div> : null}{plan.capability_notes?.map((note) => <p className="muted" key={note}>{note}</p>)}<label className="field">体验模板<select value={template || plan.recommended_template} onChange={(e) => setTemplate(e.target.value)}>{plan.compatible_templates.map((item) => <option key={item} value={item}>{item === plan.recommended_template ? `推荐 · ${item}` : item}</option>)}</select></label><div className="mode-grid"><button className="mode selected" onClick={() => setMode("quick")}>生成质量场景<small>恢复照片表面，补齐可行走结构；复杂图片会更久</small></button></div><ul>{plan.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul><div className="actions"><button disabled={busy} onClick={generate}>{busy ? "正在进入队列…" : "确认生成质量场景"}</button><button className="ghost" onClick={() => choose(null)}>更换照片</button></div></> : <p className="muted">上传后，本地AI会给出首选模板和可兼容的替代方案。</p>}</div>
    </section>
    {job && <section className="card result"><div><h2>03 · 体验与交付</h2><p>{statusLabel} · 阶段 {job.progress}%</p>{job.stage_timings_ms && Object.keys(job.stage_timings_ms).length ? <p className="muted">实际生成耗时：{Object.entries(job.stage_timings_ms).map(([stage, ms]) => `${stage} ${(ms / 1000).toFixed(1)}秒`).join(" · ")}</p> : null}{job.validation_status !== "passed" && <p className="notice">质量验收：{job.validation_status === "failed" ? "未通过" : job.validation_status === "needs_review" ? "待复核" : "尚未验收"}。生成完成不等于质量通过。</p>}{job.state === "INTERRUPTED" && <p className="notice">任务因进程重启而中断；当前未提供断点续算，请保留这条记录并重新确认生成。</p>}{job.state === "CANCELLED" && <p className="notice">任务已取消；已完成的快速结果仍可查看，完整版不会自动替换它。</p>}{job.state === "QUICK_READY" && job.generation_mode === "progressive" && !job.error && <p className="notice">快速版已经可以玩，完整版正在后台顺序生成。</p>}{job.error === "FULL_UPGRADE_NOT_PROMOTED" && <p className="notice">完整版候选已保留，但未通过安全升级条件；当前继续使用快速版。</p>}{job.error === "FULL_MACHINE_QUALITY_FAILED" && <p className="notice">完整版机器检查未通过；当前继续使用快速版，失败候选已保留供复核。</p>}{job.state === "FULL_READY" && <p className="notice">完整版候选已完成；仍需同一路线浏览器复核，不能仅凭分辨率宣称完成。</p>}{manifest && <p className="notice">{manifest.generated_region_note}</p>}{manifest && <p className="muted">机器检查：{manifest.quality_status === "failed" ? "失败" : manifest.quality_status === "needs_visual_review" ? "通过基础结构检查，仍需视觉复核" : "未完成"}。{manifest.coverage == null ? "几何覆盖率未测量。" : `可见覆盖率 ${(manifest.coverage * 100).toFixed(1)}%。`}</p>}</div><div className="progress"><span style={{ width: `${job.progress}%` }} /></div>{job.scene_id && sceneObjectUrl && manifest && (manifest.experience_kind === "interactive_subject" && preview ? <SubjectViewer key={manifest.scene_id} preview={preview} actions={manifest.actions} regions={manifest.subject_regions} /> : !manifest.mock && !manifest.camera ? <p className="notice">这是旧版本真实场景，没有新版相机协议，已停止展示。请重新上传照片并生成新版场景。</p> : <SceneViewer key={manifest.scene_id} objectUrl={sceneObjectUrl} manifest={manifest} />)}<div className="actions">{["QUEUED", "QUICK_GENERATING", "FULL_GENERATING"].includes(job.state) ? <button className="ghost" onClick={cancel} disabled={busy}>取消任务</button> : null}{job.state === "FAILED" || job.state === "INTERRUPTED" || job.state === "CANCELLED" ? <button onClick={retry} disabled={busy}>重新生成</button> : null}{job.scene_id && <a className="button" href={apiUrl(`/api/scenes/${job.scene_id}/scene.glb`)} download>下载 GLB</a>}{job.scene_id && <a className="button" href={apiUrl(`/api/scenes/${job.scene_id}/export`)} download>导出当前包</a>}</div></section>}
    {error && <p className="error global">{error}</p>}<footer>照片只在本机处理；不可见区域会标注为AI创作，不宣称真实空间复原。当前单GPU队列一次只运行一个模型任务。</footer></main>;
}
