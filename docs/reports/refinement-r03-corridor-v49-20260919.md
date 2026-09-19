# R03 走廊材质与灯光候选记录

日期：2026-09-19
状态：候选生成与技术验收完成，等待用户视觉确认

## 目标

在 V48 的几何和路线基础上，让墙、地面、木门、玻璃、金属和灯具在远看与移动中更容易区分。R03 不删除对象、不改变相机、不改变碰撞和路线。

## 变更

- 新模块：`backend/app/services/material_refinement.py`
- 构建脚本：`backend/scripts/build_refined_corridor_v49.py`
- 灯光预设：`indoor_pixel_detail_v5`
- 材质策略：`role_based_contrast_preserve_v48_geometry`
- V49 继承 V48 的 3470 个对象和 6 个碰撞盒。
- 实际调整 2624 个语义材质实例；未删除 V48 对象。

## 技术证据

- 定向测试：`2 passed`。
- 全量后端回归：`87 passed`；仅有 pytest cache 权限警告。
- 离线 ZIP：约 1.10 MB。
- 正式 `offline-verify`：`all_offline_verification=pass`。
- 真实 `file://` 起点、中段、右移、尽端和复位路线实测：无页面错误、无控制台错误；运行记录位于 `pixel-v49-refinement/route-runtime/`。
- V49 与 V48 的起点、边界、检查点和碰撞盒保持一致。

## 视觉观察

- 起点：墙面不再与地面完全同一明度，木门与黑色金属边框的层次更清楚。
- 右侧近看：木门的暖色面、黑色横向扶手、玻璃/金属格栅更容易分辨。
- 移动中：地面接缝仍保留，未用统一暗色遮住原有细节。
- 限制：这是材质与灯光候选，不是新的几何重建；远端结构和整体风格仍继承 V47/V48。

## 尚未完成

1. 需要用户确认 V49 的颜色和对比是否比 V48 更合适。
2. 还没有在真实 GPU 设备上做帧率基准；offline-verify 使用 SwiftShader，只能证明 file:// 可运行。
3. 用户确认前不进入 R05 客厅复用，避免把未确认的美术标准扩散到其他场景。
