# T07 街道与建筑立面前置实测

执行日期：2026-09-14

## 本次完成

- 新增 `backend/scripts/benchmark_urban.py`，把街道和建筑立面分为两个独立路线。
- 脚本只输出边缘/直线/地平线证据、叠加图和限制，不生成城市网格，也不把线段当成碰撞体。
- 补充 `backend/tests/test_benchmark_urban.py`，覆盖路线参数拒绝和保守状态输出。
- 用已有运行目录中的街道与楼体样片运行：
  - `data/urban-street.json`，街道样片的地平线候选约为 `y=0.6849`；
  - `data/urban-facade.json`，楼体样片的地平线候选约为 `y=0.4582`。

## 验收结果

| 子项 | 状态 | 证据 |
| --- | --- | --- |
| 街道线索分析 | 部分完成／待视觉 | `data/urban-street.json` 与对应叠加图 |
| 建筑立面线索分析 | 部分完成／待视觉 | `data/urban-facade.json` 与对应叠加图 |
| 独立主体分离、人车树碰撞 | 等待条件 | 仍依赖 T03 的主体工具实测，当前未接入主页面 |
| 俯拍下降、沿立面飞行 | 未完成 | 线索分析不等于场景路线，尚无通过录像 |

## 运行证据

```text
backend\\.venv\\Scripts\\python.exe scripts\\benchmark_urban.py --help  -> 0
backend\\.venv\\Scripts\\python.exe scripts\\benchmark_urban.py --image <street> --kind street --output <dir> --json <json> -> 0
backend\\.venv\\Scripts\\python.exe scripts\\benchmark_urban.py --image <facade> --kind facade --output <dir> --json <json> -> 0
```

脚本运行没有下载模型、上传照片或修改生产生成路由。中文终端若出现乱码只影响显示，不影响 JSON 的 UTF-8 内容。

## 结论与下一步

T07 只完成了不依赖显卡的结构证据前置，不能标记为街道或建筑体验完成。下一步应在独立环境中完成主体分离/建模候选实测；若仍没有合格主体提供器，保留建筑立面线索并明确街道整体未完成，不用静态人车贴片冒充可绕行场景。
