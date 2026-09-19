# Project instructions

## Scope

This repository is the student prototype for “走进照片”. The current target is the Luna execution plan: eight photo categories, four shared scene engines, local-first planning, a user-confirmed template, progressive quality modes, and an offline-shareable scene package. Any feature not in the current plan remains deferred.

## Working rules

- Preserve user changes; inspect `git status` before editing.
- Do not add deferred features (phone, hand gestures, audio, multi-photo exhibitions, movie scenes) to this release.
- Do not claim real 3D reconstruction. Clearly label AI-estimated or procedurally completed unseen areas.
- Do not call online chat APIs or upload user photos. The planner must use the pinned local Moondream model or a clearly labelled local-rules fallback.
- Keep generated artifacts and private photos out of Git.
- Prefer small, reviewable commits and meaningful verification.

## Validation language

Distinguish `mock/demo`, local-rules fallback, and real model-backed behavior in code, UI, and documentation.
- Every Luna task must state its allowed modules, forbidden modules, input/output, validation command, visual checks, rollback, and evidence.

## Offline (file://) delivery verification

`verify_export.py` 仅做包完整性检查，它的 `needs_offline_run` **不代表产物可用**。离线可运行性必须在真实浏览器里以 `file://` 打开来判定：

- 工具：`D:\CodexProjects\offline-verify\run-verify.cmd`；用法与判定标准见 `D:\CodexProjects\offline-verify\CODEX-OFFLINE-VERIFY.md`。
- 每生成一个 `*-offline.zip`，必须跑一次验证并把结果写进 manifest：

  ```bat
  python backend/scripts/verify_offline_delivery.py --catalog <run>\catalog.json --strict
  ```

  或让校验与验证一步完成：

  ```bat
  python backend/scripts/validate_pixel_delivery.py --output <run>\catalog.json --scene b01=<scene_dir> --archive b01=<zip> --verify
  ```

- 终态只看 `catalog.json` 的 `records[].offline_verification.status`（`pass`/`fail`/`skipped`）与顶层 `all_offline_verification`。
  `quality_status` 仍表示场景质量，**不**表示离线可运行性。
- 禁止用 Codex 浏览器插件/浏览器工具打开 `file://`：插件导航 URL 策略硬编码只允许 `about:blank`/`http:`/`https:`，必被拒（`navigation_url_policy_blocked`，`retryable:false`）；Chrome 扩展的「允许访问文件网址」不影响该策略。
- 验证失败时按 offline-verify 文档的处置手册修改产物（内联资源、去掉 `Worker`/`serviceWorker`/`WebAssembly.instantiateStreaming`、必要时换掉 `ImageBitmapLoader` 路径）；**不允许**通过 `--allow-file-access-from-files` / `--disable-web-security` 等放宽浏览器安全参数让验证通过。
- 报告与截图留在 `<run>\offline-verify\<scene_id>\`，作为交付证据一并引用。
