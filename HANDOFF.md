# 走进照片：交接入口

2026-09-14 · 源码交接版，非比赛成品。本页优先于历史报告中的进度声明。

本地浏览器阅读请直接双击根目录 `OPEN-HANDOFF.html`。下面的 Markdown 相对链接主要供 GitHub 和代码编辑器使用。

## 阅读顺序

1. 人类接手者： [项目说明](docs/handoff/PROJECT_BRIEF_ZH.md)，理解目标和下一步。
2. 新电脑 Codex：AGENTS.md → [工程上下文](docs/handoff/CODEX_HANDOVER.md)。
3. 初学者： [AI 协作实例](docs/handoff/AI_COLLABORATION_PLAYBOOK_ZH.md)。
4. 需要追溯时才读 docs/reports 和旧计划；不必逐篇阅读。

## 当前状态

上传、规划、SQLite 任务、MoGe/GLB 基础流程已有实现。场景侧移、回头仍有破洞和拉伸，主体动作没有合格素材。新增检查脚本不等于功能完成。

| 任务 | 已有 | 待完成 |
| --- | --- | --- |
| T00 基线 | 部分样片和设备记录 | 两图/类、固定路线录像 |
| T01 状态 | 计时、质量字段、持久化 | 完整阶段证据与实际门禁 |
| T02 查看器 | 相机、键鼠、GLB | 色彩、回头和切换验证 |
| T03 工具 | 调查、环境预检 | 合格模型产物；朋友接手分支 |
| T04 室内 | 网格、线索、实验壳层 | 墙窗直线、地面与碰撞 |
| T05 自然 | 深度/过滤/分层实验 | 连续地形和合理尺度 |
| T06 移动 | 边界、射线和相机协议 | 坡面、障碍、出生点、切换 |
| T07 城市 | 线索检查脚本 | 独立主体、立面、路线 |
| T08 主体 | 字段、视频入口、检查脚本 | 合格动作和真实区域触发 |
| T09 渐进 | 编排、独立比较脚本 | 实际增强、安全切换 |
| T10 导出 | ZIP 和完整性检查 | 双击打开、第二机性能 |

T00 是基线，T01—T10 是十项任务。不能按报告数量计算完成率。

## 新电脑演示启动

以 `D:\Projects\walk-into-photos` 为例。先准备 Python 3.12、Node 与 pnpm。以下不安装真实模型；不要复制旧 .venv。精确的已验证版本和安装顺序见 [环境记录](docs/handoff/ENVIRONMENT_VERIFIED.md)。

```powershell
cd D:\Projects\walk-into-photos
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
Copy-Item backend/.env.demo.example backend/.env
cd backend
$env:MOCK_MODE='true'
$env:MOCK_GEOMETRY='true'
$env:LOCAL_PLANNER_ENABLED='false'
$env:DATA_DIR='D:/Projects/walk-runtime-demo'
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另一个终端：

```powershell
cd D:\Projects\walk-into-photos\frontend
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1
```

打开 http://127.0.0.1:5173/；API 健康检查 http://127.0.0.1:8000/api/health。使用获授权图片。演示是测试平面，只验证流程。

真实模式需另行复制 backend/.env.real.example 到不存在的 backend/.env，修改缓存路径和开关；已有 .env 勿覆盖。`.env.example` 保留作完整配置参考，不建议初学者直接使用。requirements-models.txt 已固定 MoGe 提交，但完整 GPU 环境仍需在目标电脑复核。模型与缓存放 D 盘。

## 资产与交付边界

工程包排除 .env、照片/录像、模型、虚拟环境、数据库、GLB、第三方源码副本和 Git 历史。私人案例经所有者同意单独交接。原机器运行数据未删除。

原机记录 RTX 4050 Laptop 约6GB；朋友口述 RTX4060 8GB，新电脑须复核。生成端需要模型；体验端加载结果，但浏览器性能仍需测试。远程 API 配置已预留，尚无已部署生成服务器。

导出 HTML 仍使用本地 fetch 和 ES module，file:// 双击存在限制。ZIP 文件齐全不代表可双击运行。

请先读三份专用文档并启动演示，再按 Codex 交接文档第一项任务推进。源码可提交到确认的新分支；不要删旧历史。包内 PACKAGE_MANIFEST.json 记录文件哈希。当前交付不包含自动 GitHub 推送。
