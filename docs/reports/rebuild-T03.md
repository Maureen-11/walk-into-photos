# T03 GitHub 候选工具环境审计

执行日期：2026-09-14

## 命令

```text
backend\\.venv\\Scripts\\python.exe scripts\\benchmark_asset_provider.py --json D:\\Codex\\2026-09-09\\new-chat\\walk-runtime-data\\provider-audit-2026-09-14.json
```

## 结果

- 当前机器：RTX 4050 Laptop GPU，6141 MiB，驱动 566.07。
- `sam2`、`tsr`、`hy3dgen`、`liveportrait` 均未安装。
- 本次没有下载模型，没有上传照片，没有修改生产环境。
- 审计 JSON 位于运行数据目录，不进入 Git；其中记录了候选仓库、用途、声明显存和许可证提示。
- 已将官方 TripoSR 源码放入 `third_party/TripoSR`，仅做源码和许可证审查。随后在该目录建立了隔离依赖目录，没有改动主虚拟环境；原始依赖安装在 `tokenizers` 构建阶段因本机缺少 MSVC `link.exe` 失败，改用不拉取权重的最小依赖集合后，`run.py --help` 启动超过 60 秒没有返回，已中止。
- 本次没有下载 TripoSR 权重，没有生成模型，没有读取或上传用户照片；这只能证明当前环境启动链路未通过，不能证明 TripoSR 质量可用。

## 判断

这是环境审计完成，不是生成质量通过。TripoSR 的 README 约需6GB单图，接近本机上限；Hunyuan3D完整形状加纹理约16GB，不适合直接在本机宣称可用；SAM2只负责分离；LivePortrait要单独核查动物支持和依赖。下一次候选安装必须在独立 D 盘目录、固定版本和许可记录下进行。

## 连续执行补充

本轮重新运行 `benchmark_asset_provider.py --json`，确认 GPU 为 RTX 4050 Laptop、6141 MiB；四个候选均未安装，`network_or_download_performed=false`、`photos_uploaded=false`。输出证据位于 `walk-runtime-data/provider-audit-2026-09-14.json`，不进入 Git。

没有在本轮下载候选模型或权重。隔离依赖的启动阻塞需要额外的 Windows 编译工具、D 盘空间和逐项许可复核；在当前 6GB 显存上，TripoSR 的上游声明已接近上限，Hunyuan3D 完整形状加纹理明确超出本机预算。该依赖阻塞已记录，不能把主体生成标为通过；T04/T05 的无模型结构证据继续推进。
