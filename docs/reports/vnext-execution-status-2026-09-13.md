# vNext 执行进度总览

更新时间：2026-09-13
范围：用户要求“全部继续”后的本轮执行。

## 已通过的代码级结果

- 本地案例记录工具：成功／失败／部分／阻塞四种结果，独立 JSON＋Markdown 目录，敏感字段和 Windows 用户路径脱敏，重复案例不覆盖。
- 统一规划协议：区分 `spatial_scene`、`interactive_subject`、`still_fallback`；主体动作带触发方式、能力状态、冷却时间和可选目标区域。
- 本地 Moondream 规划：断网环境下雪山、街道、猫样片均能返回具体类别；普通图片仍进入规划，不因“模型不确定”直接硬拒绝。
- MoGe 真实几何路径：本机 RTX 4050 Laptop 6141 MiB 上成功生成雪山、街道、猫图 GLB。生成成功和空间体验通过已经分开记录。
- 单 GPU 调度：照片分析和几何生成共用一个 one-worker 队列；创建任务有锁，避免并发检查与入队竞争。
- 重启与失败处理：运行中任务重启后标为 `INTERRUPTED`；失败／中断任务保留旧记录，并提供重新排队接口。
- 空间控制协议：地面跟随、起点重置 `R`、飞行 `F`、路线检查点和碰撞半径字段已接通；随机粒子装饰已移除，避免伪装成空间补全。
- 离线导出：导出包现在包含 `index.html`、`scene.glb`、`manifest.json`、本地 Three.js、GLTFLoader 和 README，不引用 CDN、API 或模型权重；缺依赖时不生成不完整包。

## 真实验证结果

```text
后端 pytest：14 passed, 1 warning
前端 TypeScript：通过（tsc --noEmit --incremental false）
前端生产构建：通过（pnpm run build）
本机 GPU：NVIDIA GeForce RTX 4050 Laptop GPU，6141 MiB，驱动 566.07
```

pytest 的唯一警告是 Windows 无法写入既有 `backend/.pytest_cache`；没有删除缓存来掩盖问题。前端生产构建需要允许 Vite 写入临时缓存文件，构建本身已经通过。

## 尚未完成或明确阻塞

### 主体动画

当前环境没有 `liveportrait`、`onnxruntime` 或动物动作权重。Moondream 和 MoGe 不能代替局部动作模型。因此猫咪／人物／物品没有被标为完成；前端只有在存在真实动作素材且状态为 `available` 时才播放，否则保留原图并提示待验收。

阻塞案例：

`D:/Codex/2026-09-09/new-chat/walk-runtime-data/cases/subject-response-blocked-001`

官方 LivePortrait 仓库说明其动物模式依赖 X-Pose，且 Windows 上需要单独核查 CUDA／依赖；仓库还提示较高 CUDA 版本可能有未知问题。因此不能直接把它装进当前 MoGe 环境，更不能未经许可证和显存测试就宣布成功。[官方 LivePortrait 仓库](https://github.com/KlingAIResearch/LivePortrait)

### 空间体验

MoGe GLB 已生成，但还没有浏览器录屏证明雪山能沿雪地前进、绕过障碍并回头观察稳定环境。当前碰撞字段和边界仍是协议／限幅，不能称为已验证的网格碰撞。

空间部分案例：

`D:/Codex/2026-09-09/new-chat/walk-runtime-data/cases/spatial-moge-snow-001`

### 视觉验收

后端和前端开发服务器均能启动；但浏览器自动化服务两次返回 `nodeRepl.fetch request failed`，无法取得截图和拖拽后的真实页面状态。因此本轮没有把页面截图、场景行走或离线包跨电脑打开标为视觉通过。

### 八类完整覆盖

八类规划映射和测试已存在，但每类至少两张图片、不同视角、主体动作或场景路线的完整验收尚未完成。当前不能宣称“八类全部完成”。

### 完整／渐进质量

`full` 现在是重新计算几何的候选版本，并明确标为 `candidate`；还没有纹理补全、遮挡区域质量对比或同坐标切换的人工证据。快速／完整／渐进的状态和失败保护已接通，但质量升级仍未通过。

## 下一阶段唯一允许的路线

1. 在不改现有 MoGe 环境的独立目录中，核查并决定是否安装 LivePortrait 动物模式；先做一个无遮挡猫，再做第二张猫，最后做笼中双猫。任何一个失败都保留失败案例。
2. 重新启动本地前后端，完成雪山和室内的固定路线录屏；检查前进、绕障、回头、R 重置和版本切换。
3. 用第二台 RTX 4060 8GB 机器重复关键样片，记录真实显存、耗时和失败原因。
4. 最后再扩展八类、质量升级和跨电脑离线包，不能用规划字段代替体验证据。
