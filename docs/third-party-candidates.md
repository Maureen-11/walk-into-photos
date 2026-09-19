# 外部候选工具记录

本文件只记录候选来源与许可证，不把外部源码、模型权重或生成资产提交进项目。

| 工具 | 本地用途 | 来源 | 许可证／边界 | 状态 |
| --- | --- | --- | --- | --- |
| TripoSR | 单个动物、人物或物品的形状对照 | https://github.com/VAST-AI-Research/TripoSR | MIT；官方 README 声明单图约6GB显存 | 源码已在本地独立目录审查，依赖与权重未安装 |
| SAM 2 | 主体分离 | https://github.com/facebookresearch/sam2 | Apache-2.0/BSD-3-Clause 组件 | 未安装 |
| Hunyuan3D-2 | 物体形状／纹理候选 | https://github.com/Tencent-Hunyuan/Hunyuan3D-2 | Tencent Hunyuan 3D 社区许可；完整形状＋纹理显存需求高 | 未安装 |
| TRELLIS.2 | 高质量物体生成对照 | https://github.com/microsoft/TRELLIS.2 | 官方基线至少24GB、Linux测试 | 不适合当前机器的直接路线 |
| HunyuanWorld-1.0 | 语义分层与场景组织参考 | https://github.com/Tencent-Hunyuan/HunyuanWorld-1.0 | 需按仓库许可证核对 | 只作架构参考 |
| LivePortrait | 猫／人物局部动作候选 | https://github.com/KlingAIResearch/LivePortrait | 需核对动物支持、权重和驱动素材许可 | 未安装 |

候选工具只有在独立环境中完成版本、显存、耗时、正／侧／背面和第二张照片复验后，才可接入主工程。
