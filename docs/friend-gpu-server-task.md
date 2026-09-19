# 给队友的任务：GPU生成服务器预检

## 目标

在队友的RTX 4060电脑或一台GPU服务器上，验证“服务器生成、体验机浏览器查看”的可行性。不要先改主分支，也不要把旧版3D Photo Inpainting依赖装进当前项目`.venv`。

## 先完成的最小验证

1. 启动当前后端，确认 `GET /api/health` 可访问；
2. 用雪山和走廊各上传一张照片；
3. 完成 `POST /api/analyze → POST /api/jobs → GET /api/jobs/{job_id}` 流程；
4. 记录生成耗时、峰值显存、最终 `scene_id` 和 `manifest.json`；
5. 从另一台电脑浏览器打开前端，完成加载、环顾和短距离移动；
6. 导出一个可离线打开的场景包。

## 如果测试3D Photo Inpainting

- 只在单独目录或虚拟机/WSL中操作；
- 先检查Linux/Python/PyTorch/CUDA兼容性，再考虑模型权重；
- 只用雪山和走廊各一张样片；
- 必须提供首帧、前进、侧移、回头截图或无剪辑视频；
- 记录依赖错误、显存错误和实际耗时；
- 不要把“生成视频”写成“可以自由行走”。

## 必须交付的证据

- GPU型号和显存；
- 操作系统、Python、PyTorch、CUDA版本；
- 完整命令和代码提交号；
- 输入照片SHA256；
- 每个阶段的耗时和峰值显存；
- `manifest.json`、GLB/PLY或视频路径；
- 失败时保留完整错误，不要只汇报“运行成功”。

## 接口约定

主工程接口见 [`remote-generation-contract.md`](./remote-generation-contract.md)。生成服务器必须保留任务状态、场景清单、相机和移动边界字段；如果只提供静态场景包，也要说明它是预生成资产，不是实时生成。
