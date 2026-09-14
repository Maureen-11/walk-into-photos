# T04 室内结构验收工具

执行日期：2026-09-14

## 目标与边界

本轮实现 `backend/scripts/benchmark_indoor.py`，从室内照片提取直线、水平／垂直线数量和消失点候选，并输出叠加证据图。它是结构分析工具，不是室内 3D 重建，也不把机器结果标为通过。

## 命令与结果

```text
backend\\.venv\\Scripts\\python.exe scripts\\benchmark_indoor.py --help
backend\\.venv\\Scripts\\python.exe scripts\\benchmark_indoor.py --image ..\\test-images\\corridor\\corridor-02.jpg --output data\\indoor-corridor --json data\\indoor-corridor.json
backend\\.venv\\Scripts\\python.exe scripts\\benchmark_indoor.py --image ..\\test-images\\room\\room-01.jpg --output data\\indoor-room --json data\\indoor-room.json
```

两张样片均正常退出。走廊记录 85 条线段（水平12、垂直30、斜线43），消失点候选约为 `[343.7, 295.5]`；房间记录 89 条线段（水平21、垂直20、斜线48），消失点候选约为 `[561.4, 263.1]`。叠加图和 JSON 仅保存在本地 `data/`，不进入 Git。

## 验收判断

机器分析通过，视觉结构仍为 `needs_visual_review`。这一步证明了可以把直线证据固定下来供墙地约束使用；尚未生成墙、地、顶、纹理、碰撞体，因此 T04 整体仍未通过。下一步需要用两张样片把这些证据接入独立结构实验，并录制前进、侧移、回头路线。

## 回退

脚本和证据输出独立于主生成流程；失败时停用脚本，不替换现有 GLB。OpenCV 线段输出在不同版本可能略有变化，报告保留输入与参数供复核。
