# R2：3D Photo Inpainting 官方仓库预检

日期：2026-09-14
状态：源码预检完成；未安装旧环境，未下载模型权重，未接入主工程。

## 已获取内容

- 官方仓库：[vt-vl-lab/3d-photo-inpainting](https://github.com/vt-vl-lab/3d-photo-inpainting)
- 隔离目录：`third_party/3d-photo-inpainting`
- 官方仓库ZIP：已下载到项目临时目录；因当前文件权限限制未删除，不参与运行。
- LICENSE：仓库主代码声明 MIT；依赖和模型条款仍需分别核对，不能只看主LICENSE。

## 它与我们当前代码的真正差别

当前MoGe流程是：单张深度图 → 规则网格 → 浏览器移动。它没有显式生成被遮挡区域的颜色和深度。

3D Photo Inpainting的流程是：RGB-D → Layered Depth Image（带像素连接关系）→ 深度边界分析 → 逐层颜色/深度补全 → 有限视差渲染。README明确写的是“在原视角遮挡区域合成颜色和深度”，目标是3D photo和motion parallax，不是任意距离的完整世界。

这正好针对我们当前的“洞和拉丝”问题，但不能直接证明能让用户走进雪谷深处。

## 官方资源门槛

README要求或测试环境：

- Linux（Ubuntu 18.04.4 LTS）
- Anaconda
- Python 3.7.4
- PyTorch 1.4.0
- CUDA 10.1.243
- 另有MiDaS、BoostingMonocularDepth和多组inpainting模型权重

仓库的 `download.sh` 不只是下载一个权重，还会下载四组3D Photo模型、MiDaS权重、BoostingMonocularDepth仓库和merge网络权重。当前没有下载这些权重。

## 本机预检

| 项目 | 结果 |
|---|---|
| Windows当前环境直接运行 `main.py --help` | 失败：`ModuleNotFoundError: No module named 'vispy'` |
| 当前Python | 3.12.14，与官方3.7.4不同 |
| 当前PyTorch/CUDA | 2.6.0+cu126，与官方1.4/CUDA10.1不同 |
| Conda | 未发现可用命令 |
| WSL | `wsl --status`返回访问被拒绝，未确认可用发行版 |
| 主工程 | 未修改 |

## 决策

当前不能把该仓库标记为“可直接运行”，也不能把它的MIT代码和模型权重整体当成同一许可。它值得借鉴的部分是：

1. 用显式分层和像素连接关系避免跨遮挡边界乱连三角面；
2. 对遮挡区域单独做深度/颜色补全；
3. 把运动范围限制在补全可信的有限视差内。

下一步有两个安全选项：

- **低风险**：只阅读并移植其分层/边界数据结构思想，用现有MoGe和本地OpenCV做一个小视差实验，不安装旧模型；
- **高成本**：在D盘或WSL建立独立Python 3.7/PyTorch 1.4环境，下载官方权重，跑雪山和走廊样片。该路线可能需要额外安装WSL/Conda和大量旧依赖，且仍不保证可行走。

在用户明确同意前，不执行高成本选项，也不把旧仓库依赖写入当前`.venv`。
