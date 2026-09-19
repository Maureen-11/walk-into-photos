# R02 走廊结构与细节精修候选记录

日期：2026-09-19
状态：候选生成完成；离线运行已通过，最终视觉门仍待确认

## 目标

在朋友 V47 I01 走廊基础上做增量细节层，保留原有对象、碰撞、相机起点和路线，不用粗糙重做替换朋友版本。新增范围限制在照片和 R01 清单有依据的窗户、门扇、灯具与墙面分格。

## 变更

- 新模块：`backend/app/services/detail_refinement.py`
- 构建脚本：`backend/scripts/build_refined_corridor_v48.py`
- 测试：`backend/tests/test_detail_refinement.py`
- 版本：`pixel-v48` / `pixel_style_sample_v48`
- 策略：`additive_depth_layers_preserve_v47_objects_and_collisions`
- 旧 V47 生成器、旧产物和碰撞配置没有被覆盖。

## 可复现命令

在 `backend` 目录执行：

```powershell
& ..\.venv\Scripts\python.exe -m pytest tests\test_detail_refinement.py -q
& ..\.venv\Scripts\python.exe scripts\build_refined_corridor_v48.py `
  ..\test-images\corridor\corridor-01.jpg `
  C:\Users\wuser\.codex\visualizations\2026\09\16\01a0aa4a-da3c-7fe1-b65e-fa044f377086\pixel-v48-refinement\i01
& ..\.venv\Scripts\python.exe scripts\export_pixel_sample.py `
  --scene-dir C:\Users\wuser\.codex\visualizations\2026\09\16\01a0aa4a-da3c-7fe1-b65e-fa044f377086\pixel-v48-refinement\i01 `
  --output C:\Users\wuser\.codex\visualizations\2026\09\16\01a0aa4a-da3c-7fe1-b65e-fa044f377086\pixel-v48-refinement\i01-offline.zip
& ..\.venv\Scripts\python.exe scripts\validate_pixel_delivery.py `
  --output C:\Users\wuser\.codex\visualizations\2026\09\16\01a0aa4a-da3c-7fe1-b65e-fa044f377086\pixel-v48-refinement\catalog.json `
  --scene "i01=C:\Users\wuser\.codex\visualizations\2026\09\16\01a0aa4a-da3c-7fe1-b65e-fa044f377086\pixel-v48-refinement\i01" `
  --archive "i01=C:\Users\wuser\.codex\visualizations\2026\09\16\01a0aa4a-da3c-7fe1-b65e-fa044f377086\pixel-v48-refinement\i01-offline.zip"
```

## 代码与包证据

- 定向测试：`1 passed`；仅有仓库既存的 pytest cache 权限警告。
- 全量后端回归：`86 passed`；仅有同一 pytest cache 权限警告，耗时约 2 分 47 秒。
- 离线导出单测：`1 passed`；确认 GLB 已内嵌为 base64，查看器不依赖 `fetch('./scene.glb')` 或 CDN；这仍不能替代外部工具的真实 `file://` 浏览器运行。
- 基础交付校验：通过，场景和离线 ZIP 结构完整。
- `verify_export.py`：通过包完整性检查；无原图文件、无远程 import、碰撞资源齐全。
- 正式 `offline-verify`：`all_offline_verification=pass`。真实 `file://` 页面零失败请求、零页面错误、WebGL 2.0 正常渲染；HTTP 交叉验证也通过。报告和截图位于 `offline-verify/pixel-q05-r48-i01/`。
- 路线运行脚本：`backend/scripts/record_route_runtime.mjs` 已用同一 `file://` 包运行；起点 `[0.00,1.63,5.75]`，右移点 `[1.50,1.63,3.25]`，尽端前 `[1.50,1.63,-1.65]`，尽端 `[−0.10,1.63,-6.65]`，按 `R` 后回到起点；无页面错误或控制台错误。截图和 JSON 位于 `offline-verify/pixel-q05-r48-i01/route-runtime-v2/`。
- V47 基线对象数：3418；V48 对象数：3470。
- V47/V48 碰撞盒数：均为 6。
- V48 GLB：约 2.43 MB；离线 ZIP：约 1.09 MB。
- GLB 可由 trimesh 正常加载，3470 个 geometry；场景边界为 `[[-2.6875,-0.421875,-9.765625],[2.65625,4.0,6.625]]`。
- 静态路线检查已保存为 `route-static-check.json`：起点和 4 个检查点均在移动边界内，检查点不落入中央长椅碰撞盒；这只是几何检查，不替代真实按键路线测试。
- `quality_status` 仍为 `unverified`，对象数量增加不能替代视觉质量证明。

## 未完成的验收

1. 已在本机同一浏览器视口查看 V47/V48 起点和 V48 前进、中段、右侧近墙、尽端画面：V48 的窗框、门扇、灯具和地面节奏保持可辨，未看到立即性的破洞或穿墙；这仍需要用户审美确认。
2. 当前路线脚本覆盖起点、前进、侧移、尽端和复位；还没有录制用户手动拖动环顾的视频，也没有做不同浏览器/真实 GPU 的性能结论。

## 回退与下一步

V47 仍是可回退基线。离线工具和自动路线证据已通过；下一步由用户确认 V48 的视觉精细度，再进入 R03 材质与照明。若出现遮挡、闪烁或细节反而变乱，只撤销 V48 增量层，不动 V47。
