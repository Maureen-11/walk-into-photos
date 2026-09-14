# 给新电脑 Codex 的交接上下文

先读 HANDOFF.md 与 AGENTS.md。本项目为初学者开发的“走进照片”实验原型，不能沿用历史报告中的功能完成声明。

## 目标与已确认约束

场景从原拍摄点进入有限连续空间，能前进、绕行、回头，自然景支持飞行。主体类采用预生成短动作、点击/鼠标触发，保持特征和背景。八类目标见 PROJECT_BRIEF_ZH.md。允许创作不可见区域并标识；不能声称真实复原。

所有安装与缓存优先 D 盘。照片本地处理；用户接受讨论朋友/远程生成架构，但未授权付费部署或上传照片。手机、摄像头、音乐和展览暂缓。用户偏好 Astra 写计划、Luna 实施，同一验收标准；不得声称实际切换了未切换的模型。

## 代码地图

| 文件 | 职责 |
| --- | --- |
| backend/app/main.py | API、队列、生成、manifest、导出 HTML |
| backend/app/config.py | backend/.env、路径与开关 |
| backend/app/models.py、store.py | 类型、SQLite 持久化 |
| services/photo_plan.py | Moondream 分类和区域候选、规则兜底 |
| services/geometry.py | MoGe 深度网格、相机缩放、面过滤 |
| services/templates.py | 模板和移动配置；标签不是已实现引擎 |
| services/context_shell.py | 实验壳层，未解决几何缺陷 |
| services/scene_quality.py | 结构检查，非视觉通过 |
| frontend/src/App.tsx | 上传、场景和主体查看器，仍集中在大文件 |
| backend/scripts/bakeoff | 独立算法实验 |
| backend/scripts/benchmark_*.py | 大多仅做线索/协议检查 |
| compare_scene_versions.py | 独立比较，未接入在线切换门禁 |
| verify_export.py | ZIP 完整性，不证明双击可用 |

## 必须知道的问题

1. 单视角网格在侧移后出现薄片、洞和严重拉伸。雪山不能仅靠收紧边界或壳层修好。
2. full 主要增加分辨率，尚无合格新增结构/补全；同步相机和资源仍需检查。
3. AABB 与地形射线不是完整碰撞。出生点、坡面、飞行仍未通过。
4. 主体视频入口尚无合格素材；cooldown 计时器可能提前清除播放。整只猫检测框不能当猫头框。按钮响应不等于真实目标区域交互。
5. 离线 HTML 使用 fetch 和本地 ES module；需要解决 file:// 加载或提供明确可运行方案。
6. 新增检查脚本存在局限：动作报告写 no-op 并未实测 UI；版本比较未严格证明同一输入，缺失指标也需保守处理。不要把这些脚本当正式验收门。

## 已试过的路线

MoGe 平滑/长边过滤只缓解少数面片。深度断连、三层切片对雪山没有明确改善。程序化壳层可能显示廉价灰面。3D Photo Inpainting 有源码预检，但旧环境依赖缺失，未产生合格结果。TripoSR 预检存在 rembg 等依赖和资源问题，未验证8GB成功。详情按需读 algorithm-bakeoff 报告。

## 第一项任务：可直接执行

目标：建立新电脑演示基线、确认真实模型缺件。

- 允许：独立 D 盘环境/数据、配置示例、交接测试记录。
- 禁止：覆盖已有 .env、批量重构、混装模型、上传照片。
- 输入：源码包；输出：环境版本、健康检查、上传→任务→manifest 记录。
- 命令：按 HANDOFF 启动；测试依赖 `pip install -r backend/requirements-dev.txt`；backend 下 `..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`；frontend 下 `pnpm run build`。
- 视觉：页面与演示状态一致，不把平面当三维完成。
- 回退：停止本次服务，保留原环境与数据。
- 证据：命令退出码、截图、实际失败项。完成后继续独立任务，不为小步骤重复问是否继续。

## 后续顺序

先修可独立验证的导出和动作触发，再接入朋友给出的合格几何/动作产物。选择一条场景路线，使用清晰图和困难图验证后扩展八类；最后做真实 full、新旧版本安全切换、第二电脑离线与性能验证。

朋友需提供实测 GPU/驱动、源码 commit、模型 revision、许可、输入/产物、耗时显存与失败记录。生成电脑和体验电脑可分工，不代表结果在任意电脑必然流畅。

## 资料优先级

HANDOFF 和本文件是接手入口；luna-continuous-rebuild-plan 是验收目标；旧 reports 是历史，不是功能清单。所有“通过”必须限定范围。源码包不含私人样片，缺图先列缺件，不能编造视觉通过。
