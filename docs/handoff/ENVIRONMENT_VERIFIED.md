# 已验证环境与安装顺序

更新时间：2026-09-14

这不是“任何电脑都保证一致”的锁文件，而是交接时用于对照的已验证基线。

## 本机基线

- Windows 11
- Python 3.12.14
- Node.js v24.19.0
- pnpm 11.19.0
- CUDA PyTorch：torch 2.6.0+cu126、torchvision 0.21.0+cu126
- transformers 4.56.1、accelerate 1.10.1、einops 0.8.2、pyvips 3.2.0
- opencv-python-headless 5.0.0.93
- MoGe 3.0.0，来源固定为微软 MoGe 仓库提交 `925b8ed`
- pytest 9.1.1

## 第一次演示

1. 创建新的 `.venv`，不要复制旧虚拟环境。
2. 安装 `backend/requirements.txt` 和 `backend/requirements-dev.txt`。
3. 复制 `backend/.env.demo.example` 为 `backend/.env`。
4. 启动后端 mock 模式。
5. 在 `frontend` 目录运行 `pnpm install --frozen-lockfile`。仓库中的 `pnpm-workspace.yaml` 已允许 esbuild 安装脚本，不需要手动执行 `pnpm approve-builds`。
6. 运行 `pnpm run build`，再启动 Vite。

后端导出测试需要前端依赖已经安装，因为它会读取本地查看器资产。若只做 API 单元测试，可以不启动前端，但不能据此判断离线导出完整。

## 真实模型

只有在模型依赖和权重已经缓存到 D 盘后，才复制 `backend/.env.real.example`。首次下载模型需要网络；缓存完成后再把 `LOCAL_FILES_ONLY=true` 作为断网运行开关。真实模式仍需在目标电脑记录显存、耗时和失败样片，不能把本机基线当作比赛机器保证。
