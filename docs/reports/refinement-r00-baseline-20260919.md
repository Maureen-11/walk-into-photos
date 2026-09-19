# R00 基线冻结：朋友 V47 走廊与客厅

日期：2026-09-19
本地分支：integrate/pixel-20260919
对照提交：c81d1bbf1796120b21690b0f4148f60cc1fcc8c4 (feat: add pixel v43-v47 refinement candidates)

## 可复现输入与产物

本轮确认的源照片在仓库测试素材中，生成时的哈希与 V47 layout 一致：

| 样片 | 源照片 | SHA-256 | V47 场景 | 布局对象 | 碰撞盒 |
|---|---|---|---|---:|---:|
| I01 走廊 | test-images/corridor/corridor-01.jpg | 8f431eec671ec83d0c2ae9ada2482bf417cb39be0611a31ebe9674324216f26a | outputs/pixel-v47-review/i01 | 3418 | 6 |
| I02 客厅 | test-images/room/room-01.jpg | 40e818a450085bf145eec72da0fd0d7769b7a4c6b83eb8caea86e839d54ae32b | outputs/pixel-v47-review/i02 | 3228 | 8 |

V47 对照包位于 outputs/pixel-v47-review/packages/i01-offline.zip 和 i02-offline.zip。两个 manifest 的 style_route 都是 pixel_style_sample_v47，quality_status 都是 unverified。对象数量只用于追溯，不作为“越多越好”的美术分数。

## 已实际查看的起点画面

启动对照查看器的命令：

    & .\.venv\Scripts\python.exe -m http.server 8094 --directory ..\outputs\pixel-v47-review\review

观察点使用 manifest 中的真实起点与边界：

- I01 起点 [0, 1.625, 5.75]，路线检查点为 [0,1.625,3] → [1.55,1.625,3] → [1.55,1.625,-3] → [0,1.625,-7.8]，横向边界 [-2.1,2.1]。
- I02 起点 [0, 1.625, 4.75]，路线检查点为 [0,1.625,2] → [3,1.625,2] → [3,1.625,-3.5] → [0,1.625,-3.5] → [0,1.625,-5.5]，横向边界 [-4.45,4.45]。

I01 走廊的 V47 起点已经有明显的细节密度：左右开口、门窗框、墙面装饰、地面分格、尽端窗和连续的天花灯具都能读出；这正是下一版必须守住的下限。现阶段需要改善的是材质层级和远近主次，不能把这些细节删成几块大面。

I02 客厅起点能读出大体家具、植物、窗墙和顶灯关系，沙发、桌面、墙面有多层部件。下一版重点检查家具边缘、靠背和坐垫的层次、桌面与桌腿连接、窗边光线和绕到家具侧后的连续性。

## R00 结论

1. 朋友 V47 可以作为实际视觉下限；它不是完美答案，但已有足够细节，不能被 storybook-v1 的粗模替代。
2. storybook-v1 小屋和雪谷不进入本轮对照基线，仍标记为实验草稿。
3. 开始 R02 前，必须先完成 R01 走廊细节清单，并使用同一视口、相机、输入照片与路线进行新旧对照。
4. 目录中已有的离线 ZIP 只证明包结构曾被校验；R04 必须按仓库 AGENTS.md 运行真实 file:// offline-verify，并把结果写入 catalog。
