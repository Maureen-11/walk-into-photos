# 阶段 1 测试记录

此文件只记录真实运行结果。没有测试照片、模型权重或 API Key 时，必须保留为“未测试”，不能填入推测数值。

## 测试集

| 编号 | 类型 | 文件 | 结果 | 耗时 | 备注 |
| --- | --- | --- | --- | --- | --- |
| C1 | 走廊 | 待提供 | 未测试 | — | — |
| C2 | 走廊 | 待提供 | 未测试 | — | — |
| C3 | 走廊 | 待提供 | 未测试 | — | — |
| R1 | 房间 | 待提供 | 未测试 | — | — |
| R2 | 房间 | 待提供 | 未测试 | — | — |
| R3 | 房间 | 待提供 | 未测试 | — | — |

## 阶段门槛

- 至少 4/6 张生成可识别场景；
- 至少 1 张完整走通上传、分析、生成、查看；
- 单张生成不超过180秒；
- 浏览器能够加载 GLB；
- 失败原因和回退路径有记录。

## 当前验证（2026-09-13）

- Python：语法检查通过。
- GPU：检测到 NVIDIA GeForce RTX 4050 Laptop GPU，6141 MiB 显存，驱动 566.07。
- 演示闭环：邀请码、上传、分析、生成任务、manifest、GLB 下载通过。
- 演示 GLB：608 字节，GLB 2.0 头校验通过。
- 纹理 GLB：使用临时有效 PNG 生成 1156 字节 GLB，JSON 中包含 image/texture 记录。
- 前端：Vite production build 通过。
- 输入安全：损坏图片返回400；上传内容会先解码并重新编码以去除EXIF；重复提交同一分析结果返回同一任务。

以上是工程和演示模式验证，不等同于真实 DeepSeek 或 MoGe 测试。真实6张照片结果待补充。

## 六张照片演示模式批量结果

| 文件 | 上传/分析 | 任务 | GLB大小 |
| --- | ---: | --- | ---: |
| corridor/corridor-01.jpg | 200 | READY | 18,772 B |
| corridor/corridor-02.jpg | 200 | READY | 90,444 B |
| corridor/corridor-03.jpg | 200 | READY | 43,108 B |
| room/room-01.jpg | 200 | READY | 103,080 B |
| room/room-02.jpg | 200 | READY | 80,908 B |
| room/room-03.jpg | 200 | READY | 51,856 B |

这些结果证明上传、图片重编码、演示分析、纹理GLB交付链对6张文件均可运行；不代表真实模型质量。

## DeepSeek Vision 真实分析结果

模型：`deepseek-v4-flash-vision-exp`。以下为真实 API 输出的结构化字段摘要，不包含照片内容或 Key。

| 文件 | 请求 | 适用性 | 场景 | 推荐预设 | 警告数 | 演示模式 |
| --- | ---: | --- | --- | --- | ---: | --- |
| corridor/corridor-01.jpg | 200 | suitable | corridor | corridor_forward | 4 | false |
| corridor/corridor-02.jpg | 200 | suitable | corridor | corridor_forward | 6 | false |
| corridor/corridor-03.jpg | 200 | suitable | corridor | corridor_forward | 4 | false |
| room/room-01.jpg | 200 | conditional | room | room_explore | 4 | false |
| room/room-02.jpg | 200 | conditional | room | room_explore | 5 | false |
| room/room-03.jpg | 200 | conditional | room | room_explore | 5 | false |

初步结论：6张照片均获得有效 JSON；模型能稳定区分走廊/房间并选择不同体验预设。当前样本没有触发 reject，因此还需要补充明显不适合的图片测试拒绝流程。以上只验证视觉规划，不代表 MoGe 几何质量。
