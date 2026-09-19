# R2：GitHub 候选算法资源与许可预检

日期：2026-09-14
状态：仅做官方仓库资料预检；未下载候选权重，未修改生产工程。

## 决策原则

本项目目标不是展示一段视频，而是让用户在本机断网后能够看、走、绕、回头看。候选只有在同时满足以下条件时，才允许进入独立样片实测：

1. 有可核验的官方代码和运行入口；
2. 在 RTX 4050 6GB / 队友报告的 RTX 4060 8GB 上有现实的显存路径；
3. 代码、权重和用途许可允许本项目用途；
4. 输出能够保留相机、尺度和碰撞代理，不能只得到一张视频或一个静态截图。

## 候选结果

| 候选 | 可借鉴内容 | 当前决定 | 原因 |
|---|---|---|---|
| [3D Photo Inpainting](https://github.com/vt-vl-lab/3d-photo-inpainting) | 单图分层、深度边界和遮挡区域补全；可输出有视差的网格 | `candidate_small_parallax` | MIT；更适合前后景小视差和补洞对照，不宣称能生成整条可漫游山谷；原仓库环境较旧，需要隔离验证 |
| [TripoSR](https://github.com/VAST-AI-Research/TripoSR) | 对猫、人物、食物等单主体生成静态网格 | `candidate_subject` | 官方说明默认约6GB显存；可作为主体支线，不适合雪山/走廊/街道；动作和鼠标交互仍需项目自己的动画/交互层 |
| [FlashWorld](https://github.com/imlixinyang/FlashWorld) | 单图/文字生成3D Gaussian场景，适合研究“场景扩展”路线 | `blocked_hardware_unverified` | README中的低显存配置仍约9GB、约10分钟（A800参考）；没有核验8GB Windows离线路径前不安装 |
| [WonderWorld](https://github.com/KovenYu/WonderWorld) | 通过深度和生成扩展从新视角连接场景 | `blocked_hardware_48GB` | 官方README要求约48GB GPU；明显超出本项目硬件 |
| [HY-World 2.0](https://github.com/Tencent-Hunyuan/HY-World-2.0) | 全景、轨迹规划、世界扩展、3D合成的分阶段设计 | `blocked_hardware_multigpu` | 官方worldgen说明面向多GPU环境，测试配置为8×H20；不能把它当作本地8GB方案 |
| [HunyuanWorld 1.0](https://github.com/Tencent-Hunyuan/HunyuanWorld-1.0) | 全景代理、语义层、网格导出和“有限世界”表达 | `borrow_design_only` | 值得借鉴分层与代理结构；官方lite硬件说明并未验证本机8GB |
| [Apple SHARP](https://github.com/apple-aiml-research/ml-sharp) | 单图3D Gaussian和近距离新视角 | `blocked_license_product_development` | 官方模型许可限研究用途，明确排除产品开发；不集成到参赛产品 |
| [Spark](https://github.com/sparkjsdev/spark) | 浏览器中显示Gaussian，与mesh共存 | `candidate_viewer_only` | MIT，但只负责显示，不生成背面、不提供碰撞，也不能修复当前MoGe网格 |

## 能直接借用什么

可以借用的是**算法结构和工程分层**，不是未经验证的大模型权重：

- 从3D Photo Inpainting借用“前景/中景/背景分层 + 深度边界断开 + 遮挡区域单独补全”的思路，用于近距离视差和有限绕行；
- 从HunyuanWorld借用“全景代理、语义层、网格/高斯显示分开”的接口设计，把可见照片表面、生成区域和碰撞代理分开记录；
- 从TripoSR借用“主体先分割、单独建模、再挂到场景”的主体流程，不让猫或人物被整张照片的深度网格拉成长条；
- 从Spark借用查看器适配思路，但只有在我们确认Three.js版本兼容后才增加Gaussian显示分支。

## 不应直接借用

- 不复制WonderWorld或HY-World 2.0的多GPU世界生成路线；本机显存和时间不满足。
- 不把FlashWorld的A800低显存数字改写成“8GB可运行”；在未实测前只能写资源受阻。
- 不把SHARP模型下载进产品；研究许可证与参赛产品用途不一致。
- 不把静态TripoSR网格叫作“猫会动了”；动画、点击回应和摄像头手势是独立任务。

## R2 小任务输出

下一步只允许做以下一件事：在D盘建立隔离环境，对3D Photo Inpainting和TripoSR先运行官方 `--help` 或最小入口检查，不下载大权重、不上传照片、不改主工程。若依赖或显存门槛不通过，保存失败日志并转为“借鉴设计”，不得继续盲装。FlashWorld、WonderWorld、HY-World、SHARP暂不安装。

## 本机预检记录

- `third_party/TripoSR` 已存在于隔离目录，但使用项目当前 `.venv` 运行官方入口时缺少 `rembg`，命令在导入阶段即停止：`ModuleNotFoundError: No module named 'rembg'`。
- 尝试使用仓库附带的 `.python` 依赖目录运行 `--help`，导入阶段长时间无输出，未继续等待或下载权重，已主动停止；因此不能写成“TripoSR可运行”。
- `3D Photo Inpainting` 当前未放入本地隔离目录；没有为了这次预检自动克隆或安装其旧版依赖。

当前真实状态：`TripoSR=blocked_dependency`，`3D Photo Inpainting=not_installed`。这不否定它们的算法价值，只表示下一次要先准备明确的隔离依赖和最小样片，再测显存与输出格式。

## 与当前MoGe的借鉴验证

在没有安装旧版3D Photo Inpainting之前，先用现有MoGe预测做了一个三层深度候选实验，作为分层思想的最低成本对照。雪山长宽比P99从当前约9.82升至14.84，走廊约6.95、接近原版本6.68；因此“分三层”本身不能修复雪山，也没有理由直接接入主工程。详细数据见 `algorithm-bakeoff-r1-layered-2026-09-14.md`。

当前建议：空间类暂停继续调分层阈值；若继续投入，转为真正的遮挡颜色/深度补全或可验证的连续场景表示。主体类另行做TripoSR隔离预检，不能把两条路线混成一个生成器。
