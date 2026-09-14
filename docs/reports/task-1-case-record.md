# 任务 1：统一案例记录最小基础

执行日期：2026-09-13
状态：已完成当前任务卡；未开始任务 2／3。

## 交付内容

- `backend/app/services/case_record.py`：本地案例记录模型、敏感字段／路径脱敏、独立目录写入与读取校验。
- `backend/scripts/new_case.py`：可从仓库根目录或 `backend` 目录直接运行的本地 CLI。
- `backend/tests/test_case_record.py`：成功／失败文件、脱敏、路径校验和重复案例保护测试。

每个案例目录包含：

```text
<root>/<case-id>/
  case.json
  README.md
  evidence/
  input/
```

该工具不接入生产 SQLite，不上传 GitHub，不移动或删除照片。已有案例不会被同 ID 静默覆盖；复测应使用新的案例 ID。

## 验收证据

| 检查 | 结果 |
| --- | --- |
| `backend` 中 `..\\.venv\\Scripts\\python.exe -m pytest -q tests/test_case_record.py` | `3 passed, 1 warning` |
| `backend` 中 `..\\.venv\\Scripts\\python.exe -m pytest -q` | `7 passed, 1 warning` |
| 直接运行 `scripts/new_case.py` 创建临时案例 | `cli_case_file: PASS`，退出码 0 |
| 敏感值检查 | `token` 字段值不写入；绝对 Windows 路径缩减为 `<local>/<filename>` |
| 既有工程编译／构建 | 未在本任务重复宣称通过；任务 0 已记录 `compileall` 的既有 `__pycache__` 权限阻塞和前端 `tsconfig.tsbuildinfo` 写入 EPERM |

测试警告仍是 pytest 无法写入 `backend/.pytest_cache` 的 Windows 权限问题，不影响退出码。没有删除缓存来掩盖警告。

## 尚未解决的范围

- 还没有自动从生产任务写入案例；按计划先保持独立，避免在核心流程未稳定时扩大改动。
- 还没有决定 GitHub 案例仓库名称、可见性或上传任何用户照片；后续只在用户明确选择并审核素材后处理精选案例。
- 还没有验证 6GB／8GB 模型、猫咪局部动画、场景行走或跨电脑离线包。

下一张任务卡应是任务 2 或任务 3 的独立可行性试验；每次只执行其中一张，并把输入来源、模型许可、硬件、耗时、峰值显存和真实视频写入新的案例目录。
