# 走进照片 · Luna 第一版交付说明

日期：2026-09-14

> 历史运行记录：本报告中的“邀请码”步骤已在当前入口移除，当前本地演示无需邀请码。

## 已交付

1. 本地照片分析、八类模板入口和模板对应的 engine 路由仍保留。
2. MoGe real quick 生成已经通过一次 localhost 端到端流程；manifest 包含真实相机协议、统一缩放、场景边界和 mask 覆盖率。
3. 查看器删除隐式二次缩放，使用每张照片的 FOV；移动支持环顾、WASD、R 重置、适用模板的 F 飞行，并处理斜向归一化和失焦松键。
4. quick/full 渐进流程复用 quick 的统一尺度；后台失败不会删除 quick 结果。
5. 每个真实场景目录保存本地 `mask.png` 和 `depth-preview.png` 作为复盘证据；不进入公开导出包。

## 如何运行

```powershell
cd D:\Codex\2026-09-09\new-chat\walk-into-photos\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

cd ..\frontend
pnpm dev --host 127.0.0.1 --port 5173
```

浏览器打开 `http://127.0.0.1:5173/`，直接上传照片。开发坐标面板可用 `?debug=1` 打开。

## 诚实边界

这不是八类全部通过版。真实单图几何仍只对可见表面有证据；AABB 不是家具/地形语义碰撞；主体动作和四种空间引擎还没有完成逐类视觉验收。当前低覆盖率结果会标为 `unverified`，不因为生成成功或进度 100% 就宣称能走通。

## 验证结果

- 后端：`19 passed`
- 前端：`pnpm run build` 成功
- localhost real quick：`QUICK_READY`，场景 `dfc2d7175c174c229ef42afc3df92e91`，engine `terrain`，覆盖率 `0.5788`，状态 `unverified`
- 本地服务当前监听：后端 `127.0.0.1:8000`，前端 `127.0.0.1:5173`
