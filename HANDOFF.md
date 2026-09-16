# 走进照片：交接入口

2026-09-16 · Luna 截止 9 月 19 日交付冲刺版，非比赛成品。本页优先于历史报告中的进度声明；历史报告不改写。

本地浏览器阅读请直接双击根目录 `OPEN-HANDOFF.html`。下面的 Markdown 相对链接主要供 GitHub 和代码编辑器使用。

## 阅读顺序

1. 人类接手者： [项目说明](docs/handoff/PROJECT_BRIEF_ZH.md)，理解目标和下一步。
2. 新电脑 Codex：AGENTS.md → [工程上下文](docs/handoff/CODEX_HANDOVER.md)。
3. 初学者： [AI 协作实例](docs/handoff/AI_COLLABORATION_PLAYBOOK_ZH.md)。
4. 需要追溯时才读 docs/reports 和旧计划；不必逐篇阅读。

## 当前状态（Luna 计划）

工作树：`D:/CodexProjects/walk-into-photos-luna`  · 分支：`handoff/luna-20260915`  · 基准提交：`a78122b6f179d2b5e82ff02c9ecc7c767d637ae7`。

工程可以运行，当前已接入照片支持质量路线；真实室内侧视仍需视觉复核。不要把生成结束、测试通过或候选 GLB 当作真实空间质量通过。最新回归为后端 **56 passed**、前端 `pnpm run build` 通过、`pip check` 通过；10 张素材已在本地模型环境逐张完成 Moondream 分类与 MoGe 质量路线生成。I01 已完成真实 API／浏览器／file:// 离线路线验证，但视觉质量仍保守标为待复核。P14 安全切换基础层保留，旧记录继续可读。

| 任务 | 当前事实状态 | 证据或等待条件 |
| --- | --- | --- |
| P00 | 已验证 | 112 文件清单、10 张素材哈希、独立工作树 |
| P01 | 已验证 | Python 3.12.14、依赖、Playwright、缓存路径 |
| P02 | 已验证（演示流程） | 新电脑 mock 上传→分析→任务→GLB→导出；真实模型另记 P08 |
| P03 | 已修正 | 本页与 `OPEN-HANDOFF.html` 为唯一当前入口；历史报告保留 |
| P04 | 已验证 | 生成状态与质量状态分离；旧记录默认未验证 |
| P05 | 已验证（含冲刺粗模） | 查看器焦点、投影、异步切换、失焦、碰撞和路线测试 |
| P06 | 已验证（本机） | 冲刺粗模 ZIP 断网 `file://` 双击加载、移动、重置；第二机仍未验证 |
| P07 | 机制已验证 | 缺合格真实动作视频，产品动作仍未验证 |
| P08 | 环境已验证，质量待复核 | 本轮已修正 MoGe 权重文件路径；MoGe＋API 可运行，质量仍 `needs_visual_review` |
| P09 | 未通过质量门 | 公平对照仍有空洞、拉伸和侧视不连续 |
| P10 | 未通过 | r27 把 r26 候选接入查看器后，侧移／转视出现大块黑色空区和单色墙面；候选仍未接入主路由 |
| P11–P12 | 旧精细路线等待；冲刺粗模碰撞已验证 | 旧路线仍需 P10 合格结构；本次交付使用独立参数化碰撞，不冒充精确家具重建 |
| P13 | 尚未进入 | 按计划等待室内基础路线；不同时改多个引擎 |
| P14 | 部分完成（安全层） | 已加入来源／相机／资源／验收证据合同、取消保留和 quick/full 安全阻断；完整版仍需明确质量通过与同路线视觉证据 |
| P15 | 等待条件 | 缺第二台断网电脑；不能用同一台新浏览器替代 |

## 截止交付冲刺当前结果

本轮新增路线是“照片支持质量场景”：有效图片统一进入本地规划；质量请求默认恢复 MoGe 照片投色表面，再按类别补充有限实体结构与共享碰撞布局。生成结构的墙／地／远景颜色按照片区域色带取样，避免整场景统一灰色。模型失败时才登记 `procedural_coarse`，并保留 `fallback_reason`。通用展厅不再是默认质量路线。

隔离真实模型证据：[run-20260916-planner-r1](D:/CodexProjects/luna-evidence/run-20260916-planner-r1/) 已用本机 Moondream 对 10 图分类（5 室内、2 建筑、1 自然、1 街道、1 动物）；[run-20260916-real-route-r1 报告](D:/CodexProjects/luna-evidence/run-20260916-real-route-r1/luna-real-route-report.md) 记录 I01、I02、ANIMAL 的 `moondream2-local` 分析、粗模生成、浏览器路线和导出。分类与 API 接入成功不等于真实空间几何通过，演示默认仍保留确定性的粗模兜底。

已亲自检查的证据目录：[run-20260916-coarse-route-r3](D:/CodexProjects/luna-evidence/run-20260916-coarse-route-r3/)，汇总报告为 [`luna-coarse-route-report.md`](D:/CodexProjects/luna-evidence/run-20260916-coarse-route-r3/luna-coarse-route-report.md)。其中 `batch-ten.json` 是 10 图结果，`heading-route-check.json` 覆盖 0°／90°／180°／270°／45°，`browser-check.json` 覆盖转身后 W、碰墙和 R 重置，`offline-r8-check.json` 与 `offline-r8.png` 是本机断网包检查和截图，`coarse-scene-r4.zip` 是备用演示包。

当前结论分开记录：工程运行 **通过**；自动粗模生成、相机朝向移动、实体碰撞、重置和本机离线加载 **已验证**；真实照片空间还原和视觉质量 **未通过／不宣称**；第二台电脑离线体验 **等待条件**。旧 P09/P10 的空洞、拉伸和不连续失败证据仍然有效，没有用本次粗模截图覆盖它们。


最新室内查看器路线证据：[P10 r27 报告](D:/CodexProjects/luna-evidence/run-20260915-p10-r27/P10-r27-report.md)；语义法线独立实验：[P10 r26 报告](D:/CodexProjects/luna-evidence/run-20260915-p10-r26/P10-r26-report.md)；上一轮室内线段约束证据：[P10 r25 报告](D:/CodexProjects/luna-evidence/run-20260915-p10-r25/P10-r25-report.md)；本地语义检测诊断：[P10 r23 报告](D:/CodexProjects/luna-evidence/run-20260915-p10-r23/P10-r23-report.md)；支撑像素与透视候选复核：[P10 r22 报告](D:/CodexProjects/luna-evidence/run-20260915-p10-r22/P10-r22-report.md)；前一轮透视候选诊断：[P10 r21 报告](D:/CodexProjects/luna-evidence/run-20260915-p10-r21/P10-r21-report.md)；无语义排除对照：[P10 r19 报告](D:/CodexProjects/luna-evidence/run-20260915-p10-r19/P10-r19-report.md)；I01 线段约束证据：[P10 r17 报告](D:/CodexProjects/luna-evidence/run-20260915-p10-r17/P10-r17-report.md)；前一轮线段诊断：[P10 r16 报告](D:/CodexProjects/luna-evidence/run-20260915-p10-r16/P10-r16-report.md)；最近几何候选：[P10 r15 报告](D:/CodexProjects/luna-evidence/run-20260915-p10-r15/P10-r15-report.md)。P08 Moondream 启动环境证据：[P08-r2 报告](D:/CodexProjects/luna-evidence/run-20260915-p08-r2/P08-r2-report.md)；P08 MoGe 启动环境证据：[P08-r4 报告](D:/CodexProjects/luna-evidence/run-20260915-p08-r4/P08-r4-report.md)；旧服务清理记录：[P08-r3 报告](D:/CodexProjects/luna-evidence/run-20260915-p08-r3-service-cleanup/P08-r3-service-cleanup-report.md)；P14 安全层证据：[P14 r1 报告](D:/CodexProjects/luna-evidence/run-20260915-p14-r1/P14-r1-report.md)。当前交接入口证据：[P03-r19 报告](D:/CodexProjects/luna-evidence/run-20260915-p03-r19/P03-r19-report.md)；上一轮入口复核：[P03-r18 报告](D:/CodexProjects/luna-evidence/run-20260915-p03-r18/P03-r18-report.md)；更早入口复核：[P03-r17 报告](D:/CodexProjects/luna-evidence/run-20260915-p03-r17/P03-r17-report.md)。真实 API 流程证据：[P08 Moondream API 报告](D:/CodexProjects/luna-evidence/run-20260915-p08-moondream-api/P08-moondream-api-report.md)。质量恢复报告：[quality-recovery-2026-09-16](docs/reports/quality-recovery-2026-09-16.md)；第二轮十图批处理：[quality-batch.json](D:/CodexProjects/luna-evidence/run-20260916-quality-recovery-r2/quality-batch.json)。证据目录统一位于 `D:/CodexProjects/luna-evidence`，运行产物统一位于 `D:/CodexProjects/luna-runtime`；两处均使用新的运行编号，不覆盖旧数据。

当前未合并 PR、未发布、未上传照片或模型、未删除旧数据。按本轮用户授权，代码已同步至 GitHub 独立分支 `handoff/luna-20260915`；F 盘原始交接包和照片仍只读使用。

### 质量恢复本轮证据

本轮报告：[quality-recovery-2026-09-16](docs/reports/quality-recovery-2026-09-16.md)；第一轮十图结果表：[quality-batch.json](D:/CodexProjects/luna-evidence/run-20260916-quality-recovery-r1/batch/quality-batch.json)；材质取色后的第二轮结果表：[quality-batch.json](D:/CodexProjects/luna-evidence/run-20260916-quality-recovery-r2/quality-batch.json)；I01 浏览器和离线截图位于 [quality-recovery-r1](D:/CodexProjects/luna-evidence/run-20260916-quality-recovery-r1/)。质量场景的 `manifest.json` 记录 `photo_supported_quality`、MoGe 权重、布局版本、碰撞资源和生成区域；当前视觉状态仍是“待复核”，没有把截图写成通过。

## 新电脑演示启动

以当前工作树 `D:\CodexProjects\walk-into-photos-luna` 为例。先准备 Python 3.12、Node 与 pnpm。以下不安装真实模型；不要复制旧 .venv。精确的已验证版本和安装顺序见 [环境记录](docs/handoff/ENVIRONMENT_VERIFIED.md)。

```powershell
cd D:\CodexProjects\walk-into-photos-luna
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
Copy-Item backend/.env.demo.example backend/.env
cd backend
$env:MOCK_MODE='true'
$env:MOCK_GEOMETRY='true'
$env:LOCAL_PLANNER_ENABLED='false'
$env:COARSE_SCENE_ENABLED='true'
$env:DATA_DIR='D:/CodexProjects/luna-runtime/demo'
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另一个终端：

```powershell
cd D:\CodexProjects\walk-into-photos-luna\frontend
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1
```

打开 [http://127.0.0.1:5173/](http://127.0.0.1:5173/)；API 健康检查 [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)。使用获授权图片。当前演示走自动粗模路线：照片作为展示面与配色参考，墙、地面和障碍物为程序化实体，不代表真实空间复原。

真实模式需另行复制 backend/.env.real.example 到不存在的 backend/.env，修改缓存路径和开关；已有 .env 勿覆盖。`.env.example` 保留作完整配置参考，不建议初学者直接使用。requirements-models.txt 已固定 MoGe 提交，但完整 GPU 环境仍需在目标电脑复核。模型与缓存放 D 盘。

## 资产与交付边界

当前新电脑事实修正：实测为 RTX 4060 Laptop、显存约 8188 MiB；MoGe 与 Moondream 已在隔离模型环境本地运行，并完成缓存后的离线读取复测。Moondream 已补充真实 API 代表图验证；本轮真实路由默认使用 MoGe 照片支持质量场景，MoGe 真实画面、浏览器性能和第二机兼容性仍未完成质量验收；模型失败时才保留程序化粗模兜底。

下方的 RTX 4050／口述配置是历史原记录，按交接规则保留，不作为当前机器事实。

工程包排除 .env、照片/录像、模型、虚拟环境、数据库、GLB、第三方源码副本和 Git 历史。私人案例经所有者同意单独交接。原机器运行数据未删除。

原机记录 RTX 4050 Laptop 约6GB；朋友口述 RTX4060 8GB，新电脑须复核。生成端需要模型；体验端加载结果，但浏览器性能仍需测试。远程 API 配置已预留，尚无已部署生成服务器。

旧段落中的导出限制是历史记录。当前 P06 已验证本机断网 `file://` 双击导出包：入口自包含 manifest 与 GLB 数据，不依赖本地相对 `fetch` 或模块导入；第二台电脑仍未验证。ZIP 文件齐全不自动代表跨机通过。

请先读三份专用文档并启动演示，再按 Codex 交接文档第一项任务推进。源码位于 `handoff/luna-20260915` 独立分支；不要删旧历史。包内 PACKAGE_MANIFEST.json 记录文件哈希。当前阶段已按授权同步代码，未同步照片、模型权重或运行数据。
