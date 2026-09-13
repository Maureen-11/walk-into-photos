import { useEffect, useMemo, useState } from "react";

type Plan = {
  analysis_id: string;
  suitability: "suitable" | "conditional" | "reject";
  scene_type: "corridor" | "room" | "other";
  title: string;
  summary: string;
  experience_preset: string;
  warnings: string[];
  estimated_seconds: number;
  mock: boolean;
};

type Job = {
  job_id: string;
  state: string;
  progress: number;
  message: string;
  scene_id?: string;
  error?: string;
};

const api = async (url: string, init?: RequestInit) => {
  const response = await fetch(url, { credentials: "include", ...init });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail ?? "请求失败");
  return body;
};

export default function App() {
  const [code, setCode] = useState("");
  const [unlocked, setUnlocked] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string>();
  const [plan, setPlan] = useState<Plan>();
  const [job, setJob] = useState<Job>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  const statusLabel = useMemo(() => {
    if (!job) return "等待确认";
    if (job.state === "READY") return "场景已准备好";
    if (job.state === "FAILED") return "生成失败";
    return job.message || "处理中";
  }, [job]);

  async function unlock() {
    setError("");
    try { await api("/api/access", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }) }); setUnlocked(true); }
    catch (e) { setError(e instanceof Error ? e.message : "邀请码不正确"); }
  }

  function choose(next: File | null) {
    if (preview) URL.revokeObjectURL(preview);
    setFile(next); setPlan(undefined); setJob(undefined); setError("");
    if (next) setPreview(URL.createObjectURL(next));
  }

  async function analyze() {
    if (!file) return;
    setBusy(true); setError("");
    const form = new FormData(); form.append("file", file);
    try { setPlan(await api("/api/analyze", { method: "POST", body: form })); }
    catch (e) { setError(e instanceof Error ? e.message : "分析失败"); }
    finally { setBusy(false); }
  }

  async function generate() {
    if (!plan) return;
    setBusy(true); setError("");
    try {
      const created = await api("/api/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ analysis_id: plan.analysis_id }) });
      setJob(created);
      if (created.state !== "READY") {
        const latest = await api(`/api/jobs/${created.job_id}`);
        setJob(latest);
      }
    } catch (e) { setError(e instanceof Error ? e.message : "生成失败"); }
    finally { setBusy(false); }
  }

  if (!unlocked) return <main className="shell"><section className="card access"><p className="eyebrow">WALK INTO PHOTOS</p><h1>走进照片</h1><p>输入邀请码，打开一个把照片变成可探索空间的实验入口。</p><div className="row"><input value={code} onChange={(e) => setCode(e.target.value)} placeholder="邀请码" /><button onClick={unlock}>进入</button></div>{error && <p className="error">{error}</p>}</section></main>;

  return <main className="shell"><header><div><p className="eyebrow">WALK INTO PHOTOS</p><h1>把照片变成一段可以走进去的体验</h1><p className="sub">不需要写提示词。上传一张横向走廊或房间照片，AI先判断，再由你确认生成。</p></div><span className="badge">电脑体验 · 邀请制</span></header>
    <section className="grid"><div className="card upload"><h2>01 · 上传照片</h2><label className="drop">{preview ? <img src={preview} alt="待分析照片" /> : <><strong>选择一张照片</strong><span>支持 JPEG / PNG / WebP，最大10MB</span></>}<input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => choose(e.target.files?.[0] ?? null)} /></label>{file && !plan && <button disabled={busy} onClick={analyze}>{busy ? "AI正在分析…" : "让AI判断这张照片"}</button>}</div>
      <div className="card plan"><h2>02 · AI规划</h2>{plan ? <><span className={`pill ${plan.suitability}`}>{plan.suitability === "reject" ? "不建议生成" : "建议尝试"}</span><h3>{plan.title}</h3><p>{plan.summary}</p><ul>{plan.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>{plan.suitability !== "reject" && <div className="actions"><button disabled={busy} onClick={generate}>{busy ? "正在生成…" : "确认生成"}</button><button className="ghost" onClick={() => choose(null)}>更换照片</button></div>}</> : <p className="muted">上传照片后，这里会出现唯一一套推荐体验方案。</p>}</div></section>
      {job && <section className="card result"><div><h2>03 · 体验与交付</h2><p>{statusLabel}</p>{job.state === "READY" && <p className="notice">当前为演示几何；真实模式会替换为MoGe生成结果，并继续检查可移动范围。</p>}</div><div className="progress"><span style={{ width: `${job.progress}%` }} /></div>{job.scene_id && <div className="actions"><a className="button" href={`/api/scenes/${job.scene_id}/scene.glb`} download>下载 GLB</a><a className="button ghost" href={`/api/scenes/${job.scene_id}/manifest`} target="_blank" rel="noreferrer">查看场景信息</a></div>}</section>}
      {error && <p className="error global">{error}</p>}<footer>照片不可见的部分会由AI估计补全，不代表真实空间重建。原图和中间文件不会作为项目素材公开保存。</footer></main>;
}
