# T10 导出与性能前置验收

执行日期：2026-09-14

## 本次实测

- `backend/scripts/verify_export.py --help` 通过。
- 检查 `walk-runtime-data/offline-check-2026-09-14.zip`：37,299,807 bytes。
- 检查 `walk-runtime-data/exports/snow-378c.zip`：7,228,939 bytes。
- 两个包都包含 `index.html`、`scene.glb`、`manifest.json`、查看器依赖和 README；不含 `source.jpg`，不含远程 import。
- 两个包的自动状态都是 `needs_offline_run`，不是 `passed`。

## 尚未完成

- 还没有在第二台电脑断网双击打开并记录首次加载时间、路线移动和帧率。
- 仍没有八类各两张照片的完整通过矩阵。
- 包完整性不能证明雪山或室内网格本身质量通过。

## 结论

T10 的包内容检查已可重复运行，但交付验收仍等待第二台电脑实测。未经该实测，不报告“可在评委电脑离线运行”。
