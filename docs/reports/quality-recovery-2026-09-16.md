# Luna 质量恢复执行记录（2026-09-16）

## 当前实现

本轮把真实非 mock 生成从固定粗模优先改为照片支持质量路线：

`分析 → MoGe 深度与相机 → 照片表面保留 → 类别结构补全 → 共享碰撞布局 → 机器检查`

MoGe 生成的相机空间照片投色表面不再被固定房间替换。室内、自然、街道和建筑分别添加有限的地面、边界、远景或体块；程序化结构与碰撞盒由同一布局描述生成。MoGe 失败时才进入 `procedural_coarse`，并在 manifest 的 `fallback_reason` 中保留失败类型。

新请求默认 `quality_route=true`，仍兼容旧的 quick/full 任务记录。可选 `region_confirmations` 会参与布局证据与辅助标注哈希。manifest 新增质量路线、人工辅助、照片支持区域、生成区域和模型来源字段。

前端提供可选区域确认：选择地面、墙面／边界或主要障碍后在照片上点击一次；确认框随任务请求传入并写入 `layout.json` 与 manifest 哈希。默认不点击仍保持全自动。

## 已验证

命令记录（均退出码 0，工作树 `D:/CodexProjects/walk-into-photos-luna`）：

- `backend`: `..\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider`
- `backend`: `..\\.venv\\Scripts\\python.exe -m compileall -q app tests scripts`
- `backend`: `..\\.venv\\Scripts\\python.exe -m pip check`
- `frontend`: `pnpm run build`
- 模型环境：`.venv-models\\Scripts\\python.exe scripts/run_quality_batch.py --photos F:/walk in photo/pictures --output D:/CodexProjects/luna-evidence/run-20260916-quality-recovery-r1/batch`
- 离线包：`backend/scripts/verify_export.py --package .../offline-i01/scene.zip --json .../verify-export.json`

- 后端：55 项测试通过；Python 语法解析通过；pip check 通过。
- 前端：TypeScript 与 Vite build 通过。
- 本地 MoGe：使用 `moge-2-vits-normal/model.pt`，I01 真实质量路线生成成功。
- 本地 API：Moondream 分类为 `indoor_space`，进入 `indoor_walk`；质量路线耗时约 12 秒（本机实测，不作为质量保证时限）。
- 十图批处理：10/10 进入 `photo_supported_quality`，分类为室内 5、建筑 2、自然 1、街道 1、动物 1；本轮没有质量路线失败或静默粗模兜底。
- 四类 API 代表样片：室内、自然、街道、建筑均为 `QUICK_READY`，provider 均为本地 MoGe＋photo-structure；机器状态统一为 `needs_visual_review`，不是质量通过。
- 浏览器：I01 无控制台错误；初始照片表面可辨认；W 移动位置改变；转向后 W 仍按当前视线移动；R 回到 `[0,0,0]`。
- 初步视检：起点照片表面已恢复；侧后视角由生成结构填充，但仍需继续改善纹理连续性与家具/墙面细节，当前状态为待视觉复核，不写作质量通过。

## 保留的失败与限制

- 质量路线浏览器插件连接因运行时引用不存在的浏览器服务路径而失败；本轮使用本地 Chrome 测试驱动完成同等页面检查，插件问题另行登记。
- 历史最佳 GLB、录像不在 F 盘交接包中，当前使用固定交接提交和本地权重重新生成，不能声称复现旧机器最佳产物。
- 单张照片不可见区域仍是估计补全；没有第二机证据时，跨机状态保持未验证。

API 四类登记：[api-four.json](D:/CodexProjects/luna-evidence/run-20260916-quality-recovery-r1/api-four.json)；十图批处理：[quality-batch.json](D:/CodexProjects/luna-evidence/run-20260916-quality-recovery-r1/batch/quality-batch.json)。
