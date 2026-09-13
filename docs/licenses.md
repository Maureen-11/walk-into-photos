# 第三方许可证登记

> 说明：本文只记录**已经核实**的许可证结论，供路线选型与比赛材料引用。
> 数据采集时间：2026-09-13，来源为 GitHub 仓库元数据与仓库根目录的 LICENSE 文件。
> 上游随时可能变化，正式引用前请复核。

## 1. 为什么要单独记这份

在比赛材料里写"我们使用了某个模型"之前，需要先知道能不能这么用。研究项目的代码许可差异很大：有的是标准宽松许可，有的是自定义条款，有的干脆没有 LICENSE 文件——而没有 LICENSE 不等于随便用，默认状态是保留所有权利。这份登记把候选项目按"能不能用"分成三类，避免把不能用的东西写进材料。

## 2. 判定口径

- **可直接用**：MIT、Apache-2.0、BSD 等标准宽松许可。
- **需谨慎**：自定义条款或非商用许可。用于学生学习与小范围演示通常可行，但必须逐条阅读，且不能假定可商用、可再分发模型权重。
- **不可直接用**：仓库没有 LICENSE 文件，默认保留所有权利。只能参考思路与方法，不能复制代码，也不能随我们的产物分发其权重。

## 3. 模型与算法

| 项目 | 用途 | 许可证（实测） | 判定 |
|---|---|---|---|
| [apple-aiml-research/ml-sharp](https://github.com/apple-aiml-research/ml-sharp) | 单图 → 3D 高斯 | Apple 自定义条款 | 需谨慎 |
| [Stability-AI/stable-virtual-camera](https://github.com/Stability-AI/stable-virtual-camera) | 少图 → 新视角视频 | Stability AI 非商用许可 | 需谨慎（明确非商用） |
| [KovenYu/WonderWorld](https://github.com/KovenYu/WonderWorld) | 单图 → 可漫游场景 | 无 LICENSE 文件 | 不可直接用 |
| [KovenYu/WonderJourney](https://github.com/KovenYu/WonderJourney) | 场景序列漫游 | MIT | 可直接用 |
| [EnVision-Research/LucidDreamer](https://github.com/EnVision-Research/LucidDreamer) | 单图 → 3D 场景 | MIT | 可直接用 |
| [wenqsun/DimensionX](https://github.com/wenqsun/DimensionX) | 单图 → 3D/4D 场景 | Apache-2.0 | 可直接用 |
| [THU-SI/ReconX](https://github.com/THU-SI/ReconX) | 稀疏视角重建 | MIT（代码尚未发布） | 待观察 |
| [lukasHoel/text2room](https://github.com/lukasHoel/text2room) | 文本/图 → 房间网格 | MIT | 可直接用 |
| [vt-vl-lab/3d-photo-inpainting](https://github.com/vt-vl-lab/3d-photo-inpainting) | 单图 3D 摄影（分层深度） | 非标准许可 | 需谨慎 |
| [VAST-AI-Research/TripoSR](https://github.com/VAST-AI-Research/TripoSR) | 单图 → 网格 | MIT | 可直接用 |
| [TencentARC/InstantMesh](https://github.com/TencentARC/InstantMesh) | 单图 → 带贴图网格 | Apache-2.0 | 可直接用 |
| [thu-ml/CRM](https://github.com/thu-ml/CRM) | 单图 → 网格 | MIT | 可直接用 |
| [3DTopia/LGM](https://github.com/3DTopia/LGM) | 多视角 → 高斯 | MIT | 可直接用 |
| [VAST-AI-Research/MIDI-3D](https://github.com/VAST-AI-Research/MIDI-3D) | 单图 → 多物体场景 | Apache-2.0 | 可直接用 |
| [Tencent-Hunyuan/Hunyuan3D-1](https://github.com/Tencent-Hunyuan/Hunyuan3D-1) | 单图/文 → 3D | 非标准许可 | 需谨慎 |
| [szymanowiczs/splatter-image](https://github.com/szymanowiczs/splatter-image) | 单图 → 高斯 | BSD-3-Clause | 可直接用 |
| [DepthAnything/Depth-Anything-V2](https://github.com/DepthAnything/Depth-Anything-V2) | 单目深度估计 | Apache-2.0 | 可直接用 |
| [ByteDance-Seed/Depth-Anything-3](https://github.com/ByteDance-Seed/Depth-Anything-3) | 单目深度估计 | Apache-2.0 | 可直接用 |
| [apple-aiml-research/ml-depth-pro](https://github.com/apple-aiml-research/ml-depth-pro) | 米制深度 | Apple 自定义条款 | 需谨慎 |
| [microsoft/MoGe](https://github.com/microsoft/MoGe) | 单图几何 | 非标准许可 | 需谨慎 |
| [prs-eth/Marigold](https://github.com/prs-eth/Marigold) | 扩散式深度 | Apache-2.0 | 可直接用 |
| [lpiccinelli-eth/UniDepth](https://github.com/lpiccinelli-eth/UniDepth) | 通用米制深度 | 非标准许可 | 需谨慎 |
| [isl-org/ZoeDepth](https://github.com/isl-org/ZoeDepth) | 米制深度 | MIT | 可直接用 |
| [isl-org/MiDaS](https://github.com/isl-org/MiDaS) | 单目深度 | MIT | 可直接用 |
| [facebookresearch/vggt](https://github.com/facebookresearch/vggt) | 多视图几何 | 非标准许可 | 需谨慎 |
| [facebookresearch/map-anything](https://github.com/facebookresearch/map-anything) | 多视图重建 | Apache-2.0 | 可直接用 |
| [naver/dust3r](https://github.com/naver/dust3r) | 无位姿点云 | 非标准许可 | 需谨慎 |
| [naver/mast3r](https://github.com/naver/mast3r) | 匹配与重建 | 非标准许可 | 需谨慎 |

## 4. 浏览器渲染与工具链

| 项目 | 用途 | 许可证（实测） | 判定 |
|---|---|---|---|
| [playcanvas/supersplat](https://github.com/playcanvas/supersplat) | 高斯编辑器与查看器 | MIT | 可直接用 |
| [sparkjsdev/spark](https://github.com/sparkjsdev/spark) | Three.js 高斯渲染器 | MIT | 可直接用 |
| [mkkellogg/GaussianSplats3D](https://github.com/mkkellogg/GaussianSplats3D) | Three.js 高斯渲染器 | MIT | 可直接用 |
| [antimatter15/splat](https://github.com/antimatter15/splat) | WebGL 高斯查看器 | MIT | 可直接用 |
| [huggingface/gsplat.js](https://github.com/huggingface/gsplat.js) | 高斯加载与渲染 | MIT | 可直接用 |
| [quadjr/aframe-gaussian-splatting](https://github.com/quadjr/aframe-gaussian-splatting) | A-Frame / WebXR 查看 | MIT | 可直接用 |
| [houmahani/codrops-depth-gallery](https://github.com/houmahani/codrops-depth-gallery) | 深度视差画廊 | MIT | 可直接用 |
| [MrForExample/ComfyUI-3D-Pack](https://github.com/MrForExample/ComfyUI-3D-Pack) | 模型流程集成 | MIT | 可直接用 |
| [graphdeco-inria/gaussian-splatting](https://github.com/graphdeco-inria/gaussian-splatting) | 3DGS 原始实现 | 非标准许可 | 需谨慎 |
| [nerfstudio-project/nerfstudio](https://github.com/nerfstudio-project/nerfstudio) | 训练与查看 | Apache-2.0 | 可直接用 |
| [nerfstudio-project/gsplat](https://github.com/nerfstudio-project/gsplat) | CUDA 光栅化 | Apache-2.0 | 可直接用 |
| [adamkuhn1/elsewhere](https://github.com/adamkuhn1/elsewhere) | 同为"单图 → 浏览器空间感"原型 | 无 LICENSE 文件 | 不可直接用 |
| `onnx-community/depth-anything-v2-small`（模型权重） | 浏览器端深度估计 | Apache-2.0 | 可直接用 |

## 5. 结论

**推荐链路（全部为宽松许可，可安全写入比赛材料）：**

Depth Anything V2 或 Depth Anything 3（Apache-2.0）→ `onnx-community` 的 ONNX 权重（Apache-2.0）→ transformers.js（Apache-2.0）→ three.js（MIT）→ Vite（MIT）。

**需要谨慎处理：**

`ml-sharp`、`ml-depth-pro`、`stable-virtual-camera`、`MoGe`、`VGGT`、`DUSt3R`、`MASt3R`、`UniDepth`、`Hunyuan3D-1`、`3d-photo-inpainting`、`gaussian-splatting`。这些项目用于课堂学习与内部对比通常没问题，但若要写进提交材料或对外演示，需要逐条阅读条款，尤其要确认是否禁止商用、是否允许再分发权重。

**不能复制代码或分发权重：**

`WonderWorld`、`elsewhere`。二者没有 LICENSE 文件，默认保留所有权利。可以参考它们的思路与公开描述，但不要复制代码，也不要把它们的产物当作我们的实现。

**引用与借鉴的边界：**

引用论文、项目主页和公开演示视频作为"相关研究与参考"是正常的学术做法；但不能把我们没有许可的模型输出描述成"我们的能力"。

## 6. 待核验

1. 比赛的官方规则是否要求提交代码使用特定开源许可？
2. 比赛是否限制使用第三方预训练模型或云端服务？
3. 是否需要为展示材料取得额外授权？

## 7. 对本仓库自身的一条建议

本仓库当前**没有 LICENSE 文件**，公开状态下默认保留所有权利，这意味着除协作者外没有人能合法复用。建议团队在第一次正式提交前决定并添加一份许可证（例如 MIT，或"保留所有权利 + 说明"），这一项应记入决策记录。

## 8. 记录规则

- 新增依赖或模型时，同步在本表补充一行；
- 标注采集日期与来源，不凭印象填写；
- 判定为"需谨慎"的项目，必须在决策记录里写明使用范围与理由。
