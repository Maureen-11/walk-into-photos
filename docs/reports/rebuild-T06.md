# T06 场景契约与机器级结构验收

执行日期：2026-09-14

## 已完成

- 新增 `backend/app/services/scene_quality.py`，对每个生成的 GLB 检查：
  - 顶点和三角形是否为空或包含非有限值；
  - 退化三角形比例；
  - 唯一边长度中位数；
  - 三角形长宽比 p99；
  - 场景边界和三个轴向跨度。
- `_generate_version` 每次生成后将检查结果写入 `manifest.json` 的 `quality_metrics`。
- `quality_status` 只会记录 `failed`、`needs_visual_review` 或 `unverified`。机器检查不直接给出 `passed`，因为走入路线、纹理拉伸、尺度和碰撞仍需浏览器人工复核。
- 前端结果区显示机器检查状态和可见覆盖率，避免把“生成结束”误读为“质量通过”。
- 离线分享包不再打包 `source.jpg`；它只包含场景、manifest、查看器依赖和隐私说明。运行目录中的原图仍受本机接口保护，用于当前会话的分析与主体候选预览，不进入分享包。
- 离线查看器读取同一份 `movement` 契约，支持 `F` 飞行、空格上升、`C` 下降和 AABB 边界夹取，不再退化成只在水平面滑动。
- 新增 `backend/scripts/verify_export.py`，会拒绝缺少核心资源、包含远程 import 或重新带入 `source.jpg` 的包；完整包仍只标记 `needs_offline_run`，不把本机 ZIP 检查冒充第二台电脑验收。
- 质量检查会先烘焙 GLB 节点变换再测量，避免把 MoGe 的本地顶点误报成超大场景；MoGe 导出前还记录深度稳定和极端长条面过滤数量。
- 室内／地形上下文壳层单独写入 `quality_metrics.context_shell`，状态固定为 `experimental_needs_visual_review`，不改变移动边界。

## 验收证据

```text
backend: 26 passed
frontend: pnpm run build 成功
backend health: 200 OK
```

对现有室内场景导出包做了本机完整性检查：约 37 MB，核心条目齐全，不含 `source.jpg`，不含远程 import，结果为 `needs_offline_run`。这不是第二台电脑的断网通过证据。

用 demo GLB 的测试确认：一个正常的平面烟测结果被标为 `needs_visual_review`，而不是伪装为 `passed`；塌缩或非有限网格会标为 `failed`。

## 尚未通过

- 真实 MoGe 场景还没有把结构检查结果和四张样片的视觉录像全部补齐。
- 该检查不会修复雪山、街景或室内的扭曲，只负责把明显错误记录下来并阻止错误的质量宣称。
- 长条面过滤只能减少最极端的三角形，不等于纹理、透视和路线视觉通过；壳层仍需侧向、回头和飞行截图。
- 第二台 RTX 4060 8GB 机器和断网导出验证仍待实际运行。
