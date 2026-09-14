# 任务 2：主体局部回应技术试验

执行日期：2026-09-13
状态：阻塞，未接入主流程。

## 检查结果

在当前 D 盘 Python 环境中检查了主体动画候选依赖：

```text
liveportrait_module=None
onnxruntime_module=None
torch_version=2.6.0+cu126
```

模型缓存中也没有 LivePortrait、Wan、WorldGen 等主体动画权重。当前工程已有本地 Moondream（规划）与 MoGe（几何）路径，但它们不能生成猫咪局部动作。

## 为什么没有直接“做一个动画”

把整张猫图抖动、缩放或播放无关视频，会破坏背景稳定性，也无法证明摸到正确猫头后产生了主体回应。这违反本项目已确认的验收标准。因此本任务没有把静态效果标为成功。

## 已完成的安全准备

- 规划协议已加入 `interactive_subject`、主体动作目录、目标区域和能力状态字段。
- Moondream 的检测接口已接成可选能力，但 `LOCAL_PLANNER_DETECT_REGIONS=false` 默认关闭；在 6GB 机器上没有完成超时／显存预算前，不让目标区域探测拖死主规划队列。
- 前端已有数据驱动的主体查看器：只有 `status=available` 且存在合法动作素材时才播放；否则显示待验收提示并保留原图。
- 已生成本地阻塞案例：`D:/Codex/2026-09-09/new-chat/walk-runtime-data/cases/subject-response-blocked-001`。

## 解锁条件

需要在独立环境核查并获准使用一个支持动物肖像局部动作的模型或合法动作素材，然后分别在无遮挡猫、第二张猫和笼中双猫上测量：定位可靠性、背景稳定性、耗时、峰值显存和回到待机的连续性。模型下载、许可证确认和 6GB／8GB 实测完成前，任务保持阻塞。
