# 参考项目清单

> 数据采集时间：2026-09-13，指标来自 GitHub API 实测。
> 星标数与更新时间会持续变化，正式引用前请复核。
> 许可证结论详见 [第三方许可证登记](licenses.md)。

本文把与"走进照片"相关的开源项目分成五层。分层的目的不是排名，而是回答一个问题：**以我们当前的人力和设备，哪一层可以直接借力，哪一层只能看不能碰。**

## 第一层：与我们的目标完全一致（单图 → 可探索场景）

| 项目 | ★ | 最近更新 | 说明与可借鉴之处 |
|---|---|---|---|
| [apple-aiml-research/ml-sharp](https://github.com/apple-aiml-research/ml-sharp) | 8885 | 2026-09-11 | 单张照片回归出 3D 高斯，官方称标准 GPU 上不足一秒，具备米制尺度。README 已引用；注意其许可证为 Apple 自定义条款 |
| [Stability-AI/stable-virtual-camera](https://github.com/Stability-AI/stable-virtual-camera) | 1661 | 2026-03-03 | 给定输入视角与目标相机位，生成新视角视频；有 HuggingFace 演示。明确为非商用许可 |
| [Drexubery/ViewCrafter](https://github.com/Drexubery/ViewCrafter) | 1593 | 2025-12-13 | 用视频扩散模型做新视角合成，少图输入，可借鉴其相机轨迹设计 |
| [wenqsun/DimensionX](https://github.com/wenqsun/DimensionX) | 1334 | 2025-10-17 | 单图生成 3D/4D 场景。README 实测约需 26–30GB 显存，超出常见设备 |
| [lukasHoel/text2room](https://github.com/lukasHoel/text2room) | 1089 | 2023-11-15 | 文本或图片生成房间网格，代码可自由使用，适合做"房间类"素材 |
| [EnVision-Research/LucidDreamer](https://github.com/EnVision-Research/LucidDreamer) | 828 | 2024-05-24 | 单图生成 3D 场景；许可证宽松，是这一层里许可最干净的候选之一 |
| [KovenYu/WonderJourney](https://github.com/KovenYu/WonderJourney) | 769 | 2024-09-20 | 场景序列漫游，MIT 许可，可借鉴"多场景叙事"的组织方式 |
| [KovenYu/WonderWorld](https://github.com/KovenYu/WonderWorld) | 741 | 2025-04-14 | 单图交互式场景漫游，官方 README 写明需要 48GB 显存；且仓库无 LICENSE 文件 |
| [THU-SI/ReconX](https://github.com/THU-SI/ReconX) | 709 | 2024-11-09 | 稀疏视角重建，MIT 许可，但 README 明示代码尚未发布 |
| [avinashpaliwal/PanoDreamer](https://github.com/avinashpaliwal/PanoDreamer) | 108 | 2026-04-24 | SIGGRAPH Asia 2025，单图生成 360° 3D 场景，适合了解全景路线的可行性 |
| [HorizonRobotics/3D-Fixer](https://github.com/HorizonRobotics/3D-Fixer) | 111 | 2026-06-22 | CVPR 2026，单图 3D 场景的补全修复，可借鉴"如何掩盖未拍摄区域"的处理策略 |
| [vt-vl-lab/3d-photo-inpainting](https://github.com/vt-vl-lab/3d-photo-inpainting) | 7092 | 2024-08-30 | 经典的"3D 摄影"：单图 → 分层深度 + 内容补全 + 视差查看。与我们第一版最接近的成熟方案，建议优先通读 |

**最贴近我们想法的已实现原型：** [adamkuhn1/elsewhere](https://github.com/adamkuhn1/elsewhere)（0★，2026-09 更新，TypeScript）。它做的事情和我们的第一版几乎重合：在浏览器内用 Depth Anything V2 Small（量化后约 19MB）经 Web Worker + ONNX Runtime Web 做深度估计，再用 WebGL 位移网格呈现，支持指针与头部视差，**照片不出本机、无服务器**，并且明确声明"这不是房间扫描"。它证明这条路线一个人就能做完。

**但要注意**：该仓库没有 LICENSE 文件，默认保留所有权利，只能参考思路，不能复制代码。

## 第二层：单图 / 少图 → 3D 资产（用来造素材）

| 项目 | ★ | 最近更新 | 说明 |
|---|---|---|---|
| [VAST-AI-Research/TripoSR](https://github.com/VAST-AI-Research/TripoSR) | 6948 | 2026-06-04 | 单图出网格，MIT 许可，上手成本低 |
| [TencentARC/InstantMesh](https://github.com/TencentARC/InstantMesh) | 4522 | 2025-01-03 | 单图出带贴图网格，Apache-2.0 |
| [Tencent-Hunyuan/Hunyuan3D-1](https://github.com/Tencent-Hunyuan/Hunyuan3D-1) | 3485 | 2025-11-19 | 单图或文本转 3D，非标准许可 |
| [3DTopia/LGM](https://github.com/3DTopia/LGM) | 2116 | 2024-08-20 | 多视角输入生成高斯，MIT 许可 |
| [szymanowiczs/splatter-image](https://github.com/szymanowiczs/splatter-image) | 1107 | 2024-08-18 | 单图出高斯，速度导向，BSD-3-Clause |
| [VAST-AI-Research/MIDI-3D](https://github.com/VAST-AI-Research/MIDI-3D) | 949 | 2025-06-12 | 单图生成多物体 3D 场景，Apache-2.0 |
| [thu-ml/CRM](https://github.com/thu-ml/CRM) | 694 | 2024-11-28 | 单图快速出带贴图网格，MIT 许可 |

这一层更适合做"素材生产"：先用它们把少量授权照片变成网格或高斯，再交给展示层验证观感。

## 第三层：深度与几何基础模型（2.5D 路线的主力）

| 项目 | ★ | 最近更新 | 说明 |
|---|---|---|---|
| [facebookresearch/vggt](https://github.com/facebookresearch/vggt) | 14382 | 2026-05-19 | 多视图几何重建，未来扩展多图时的基础 |
| [DepthAnything/Depth-Anything-V2](https://github.com/DepthAnything/Depth-Anything-V2) | 8799 | 2026-03-24 | 单目深度估计，Apache-2.0；有浏览器可用的 ONNX 量化权重，是第一版的首选 |
| [LiheYoung/Depth-Anything](https://github.com/LiheYoung/Depth-Anything) | 8207 | 2024-07-17 | 上一代版本，生态与示例最全 |
| [naver/dust3r](https://github.com/naver/dust3r) | 7305 | 2025-09-24 | 无位姿图像直接出点云，非标准许可 |
| [ByteDance-Seed/Depth-Anything-3](https://github.com/ByteDance-Seed/Depth-Anything-3) | 6334 | 2026-07-27 | 更新一代深度基础模型，Apache-2.0，建议纳入候选 |
| [apple-aiml-research/ml-depth-pro](https://github.com/apple-aiml-research/ml-depth-pro) | 5713 | 2026-09-11 | 米制深度，速度快；许可为 Apple 自定义条款 |
| [isl-org/MiDaS](https://github.com/isl-org/MiDaS) | 5418 | 2024-08-23 | 经典方案，MIT 许可，已被上面几项超越 |
| [facebookresearch/map-anything](https://github.com/facebookresearch/map-anything) | 3734 | 2026-08-07 | 多视图重建统一框架，Apache-2.0 |
| [prs-eth/Marigold](https://github.com/prs-eth/Marigold) | 3213 | 2026-09-06 | 扩散式深度估计，质量高但速度慢 |
| [naver/mast3r](https://github.com/naver/mast3r) | 3101 | 2025-06-30 | 特征匹配与重建，非标准许可 |
| [microsoft/MoGe](https://github.com/microsoft/MoGe) | 2916 | 2026-09-09 | 单图几何估计，README 已引用；非标准许可 |
| [isl-org/ZoeDepth](https://github.com/isl-org/ZoeDepth) | 2839 | 2025-05-05 | 米制深度，MIT 许可 |
| [YvanYin/Metric3D](https://github.com/YvanYin/Metric3D) | 2316 | 2025-03-13 | 米制深度，BSD-2-Clause |
| [lpiccinelli-eth/UniDepth](https://github.com/lpiccinelli-eth/UniDepth) | 1256 | 2025-05-18 | 通用米制深度，非标准许可 |

对第一版最关键的判断：**这一层里 Depth Anything V2 是唯一同时具备"宽松许可 + 浏览器可跑量化权重 + 文档充足"三项条件的选项。**

## 第四层：浏览器端渲染与交付（容易被忽略，但决定体验）

我们的 README 目前只列了研究项目，缺了这一层。而"能不能在浏览器里跑得动、看得舒服"恰恰是演示成败所在。

| 项目 | ★ | 最近更新 | 说明 |
|---|---|---|---|
| [playcanvas/supersplat](https://github.com/playcanvas/supersplat) | 10028 | 2026-09-11 | 高斯编辑器兼网页查看器，MIT 许可，可用来快速验证高斯文件的观感 |
| [sparkjsdev/spark](https://github.com/sparkjsdev/spark) | 3606 | 2026-09-11 | Three.js 的高斯渲染器，维护活跃 |
| [antimatter15/splat](https://github.com/antimatter15/splat) | 3071 | 2025-11-16 | 极简 WebGL 高斯查看器，代码量小，一天可读通 |
| [mkkellogg/GaussianSplats3D](https://github.com/mkkellogg/GaussianSplats3D) | 2889 | 2025-10-19 | Three.js 集成度高 |
| [huggingface/gsplat.js](https://github.com/huggingface/gsplat.js) | 1664 | 2026-05-26 | 带 `.splat` 与 `.ply` 加载器 |
| [quadjr/aframe-gaussian-splatting](https://github.com/quadjr/aframe-gaussian-splatting) | 226 | 2023-12-21 | A-Frame / WebXR 组件，未来做头显体验的入口 |
| [houmahani/codrops-depth-gallery](https://github.com/houmahani/codrops-depth-gallery) | 108 | 2026-03-09 | Three.js 深度视差画廊，可作为界面与动效参考 |

## 第五层：工程加速

| 项目 | ★ | 最近更新 | 说明 |
|---|---|---|---|
| [graphdeco-inria/gaussian-splatting](https://github.com/graphdeco-inria/gaussian-splatting) | 23802 | 2025-10-17 | 3DGS 原始实现，需要多视角与位姿，**不适合单图场景**，但值得知道它的输入前提 |
| [nerfstudio-project/nerfstudio](https://github.com/nerfstudio-project/nerfstudio) | 11996 | 2025-07-29 | 端到端训练与查看框架，Apache-2.0 |
| [nerfstudio-project/gsplat](https://github.com/nerfstudio-project/gsplat) | 5672 | 2026-09-03 | CUDA 高斯光栅化库 |
| [MrForExample/ComfyUI-3D-Pack](https://github.com/MrForExample/ComfyUI-3D-Pack) | 3864 | 2025-12-29 | 把多个 3D 模型图形化串起来，是降低运行门槛的实用选择 |

## 可作为效果对照的工业产品

World Labs Marble、Luma AI、Polycam、KIRI Engine。它们能把单张照片变成可漫游空间，是这条路线商业化的参照。这些产品没有开源仓库，只能作为答辩时的对标与观感参考。

## 从这份清单得出的三条结论

1. **第一版的技术路线没有必要自己去发明。** 单图到空间化的每一步都有成熟开源实现，我们的工作重点是选型、集成与体验打磨，而不是重写算法。
2. **"能跑"和"能写进材料"是两件事。** 效果最好的几个项目（`ml-sharp`、`stable-virtual-camera`）恰好是许可证最需要注意的；而许可最干净的 `Depth Anything V2` 已经足以支撑第一版。
3. **设备门槛是最硬的约束。** `WonderWorld` 需要 48GB 显存、`DimensionX` 需要约 26–30GB，我们的 8GB 显存设备只能走浏览器端轻量方案或纯 CPU/Onnx 推理路线。这一条应当写进第一版的路线选择理由里。
