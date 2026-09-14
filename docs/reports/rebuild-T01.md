# T01 真实状态、计时与模式说明

执行日期：2026-09-14

## 已完成

- `Job` 增加 `validation_status`，默认 `not_run`；生成完成不会自动变成质量通过。
- `Job` 增加 `stage_timings_ms`、`generation_started_at` 和 `generation_finished_at`。
- quick/full 阶段使用实际 `perf_counter` 记录生成时间；前端只显示已返回的实际耗时，不再把规划估计当成实测。
- 保留快速、完整、渐进三种模式；full 仍明确显示为候选，直到视觉质检写入通过状态。

## 验收

- 后端 pytest：19 passed in 2.23s。
- 前端生产构建：通过；仅有 bundle size 警告。

## 未完成

- 质量检查器尚未接入，因此任何真实场景当前仍会显示“尚未验收”。
- 旧任务没有历史耗时字段时按空值处理，不补造时间。
