# T05 自然地形验收工具

执行日期：2026-09-14

## 目标与边界

本轮实现 `backend/scripts/benchmark_terrain.py`，记录照片中的地平线候选和近景边界，输出叠加证据图。该脚本只提供地形建模的起始证据，不生成连续地形、行走面或碰撞体，也不把室内代理样片当作雪山通过。

## 命令与结果

```text
backend\\.venv\\Scripts\\python.exe scripts\\benchmark_terrain.py --help
backend\\.venv\\Scripts\\python.exe scripts\\benchmark_terrain.py --image ..\\test-images\\corridor\\corridor-02.jpg --output data\\terrain-proxy-corridor --json data\\terrain-proxy-corridor.json
```

由于仓库当前没有用户雪山照片，运行使用走廊照片作为接口烟测代理，不作为自然场景效果证据。脚本正常退出，输出候选地平线 y=336（归一化0.56）、近景带起点 y=384，并明确标记 `needs_visual_review`。真实雪山样片缺失已记录，不能声称 T05 通过。

## 下一步

拿到本地雪山和第二张自然照片后，运行同一命令，人工检查远山／近景分界，再实现独立连续地形实验。若地平线候选不稳定，应保留失败证据并切换到人工校准或分层方案。
