# 生成服务器与体验机接口约定

目标：朋友的电脑或云GPU负责照片分析/场景生成，体验机只运行浏览器。体验机不需要安装模型权重；它只需要访问同一套HTTP接口并加载最终场景。

## 两种运行方式

### 本机模式

- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8000`
- `VITE_API_BASE_URL` 留空，Vite代理 `/api`。

### 远程生成模式

- 前端仍可运行在体验机或静态托管地址；
- 设置 `frontend/.env`：`VITE_API_BASE_URL=http://<生成服务器>:8000`；
- 服务器设置 `backend/.env` 的 `CORS_ALLOW_ORIGINS` 为体验机前端的精确来源；
- 浏览器上传照片到生成服务器，轮询任务，再从服务器加载GLB/导出包。

## 现有接口

| 阶段 | 请求 | 结果 |
|---|---|---|
| 健康检查 | `GET /api/health` | 服务器是否在线、是否本地模型、队列数量 |
| 照片分析 | `POST /api/analyze` multipart `file` | `PhotoPlan`：类别、模板、风险和能力说明 |
| 创建任务 | `POST /api/jobs` | `Job`：任务编号、模式和初始状态 |
| 查询进度 | `GET /api/jobs/{job_id}` | `QUEUED → QUICK_READY → FULL_READY` 或失败 |
| 场景清单 | `GET /api/scenes/{scene_id}/manifest` | 相机、移动边界、质量状态和场景地址 |
| 浏览场景 | `GET /api/scenes/{scene_id}/scene.glb` | GLB和纹理资源 |
| 导出 | `GET /api/scenes/{scene_id}/export` | 可双击打开的离线HTML场景包 |

朋友后续可以替换生成实现，但必须保留这些字段：`job_id`、`state`、`progress`、`quick_scene_id`、`full_scene_id`、`scene_id`、`manifest.camera`、`manifest.movement`、`quality_status`。不能用一个静态成功响应代替真实任务阶段。

## 体验机的最低要求

- 现代浏览器和WebGL；
- 能访问生成服务器；
- 不需要Python、CUDA、模型权重；
- 若使用离线导出包，则不需要API和网络。

## 服务器安全约束

- 不把 `CORS_ALLOW_ORIGINS` 设置为 `*` 与Cookie并用；
- 远程服务器应增加访问令牌或内网限制；
- 任务和上传照片设置过期清理；
- 结果包默认不包含原始照片，只保留场景纹理；
- 比赛演示必须准备预生成离线包，不能把云GPU冷启动当成唯一演示路径。

## 分工

- 朋友：实现或验证生成服务器，提交接口响应样例、耗时、显存、失败记录和场景包；
- 我们：继续维护体验端、离线包和接口兼容；
- 合并标准：先用 `/api/health`、一张雪山和一张走廊完成端到端测试，再讨论是否接入新算法。
