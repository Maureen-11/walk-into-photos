# walk-into-photos

学生团队的“走进照片”沉浸式体验项目。

我们想先从一台电脑上的可用原型开始：用户上传一张普通照片，系统生成一个可以在浏览器里观察、移动和探索的空间化场景，让人产生“走进去看一看”的感觉。第一阶段不追求真实的 3D 重建，而追求可体验、可分享、可迭代。

## 当前阶段

本仓库现在是**讨论与规划仓库**，不是已经完成的产品，也不是最终比赛报名材料。

当前优先顺序：

1. 统一项目目标和体验边界；
2. 让两位成员及各自的 AI 都能读懂同一份项目背景；
3. 用文档和 Pull Request 收集独立意见；
4. 再决定最小原型的技术路线与分工；
5. 只有在目标、体验和验收标准明确后，才开始写代码。

## 推荐阅读顺序

- [项目大纲](docs/project-outline.md)：目前的整体想法、范围、阶段目标与待确认问题。
- [AI 协作说明](AGENTS.md)：交给任意 AI 阅读的工作规则。
- [协作与分工](docs/collaboration.md)：两人如何讨论、认领任务和提交反馈。
- [决策记录](docs/decisions.md)：已经确认的选择、暂定假设和仍未决定的事项。
- [反馈模板](docs/feedback-template.md)：队友或队友的 AI 用来提交独立意见的模板。
- [场景包接口契约](docs/io-contract.md)：提案。模型侧与展示侧之间约定的中间产物格式。
- [第三方许可证登记](docs/licenses.md)：已核实的许可证结论与可用边界。
- [参考项目清单](docs/reference-projects.md)：同类开源项目的分层清单与可借鉴之处。

## 项目原则

- 先做可体验的短路径，再扩展复杂功能。
- 对真实重建、AI 补全和艺术化效果做清晰区分，不夸大能力。
- 不把“有想法”写成“已经实现”。
- 不默认上传私人照片；演示优先使用公开、获授权或专门准备的素材。
- 暂不承诺音乐、录音、热点说明、多张照片展览、电影多镜头和手机端；这些属于后续方向。
- 任何涉及付费模型、云服务或大规模素材上传的决定，先记录成本、隐私和替代方案。

## 外部参考

- [Apple ML-SHARP](https://github.com/apple/ml-sharp)：单张图片到 3D 相关研究项目，作为技术参考，不代表本项目已经采用。
- [Microsoft MoGe](https://github.com/microsoft/MoGe)：单图几何/深度相关参考。
- [Facebook Research VGGT](https://github.com/facebookresearch/vggt)：多视图/视觉几何方向参考。
- [Matt Pocock 的 grill-me skill](https://github.com/mattpocock/skills/tree/main/skills/productivity/grill-me)：本项目采用“先不断追问并确认目标，再开始实施”的讨论方式。

## 相关已有项目

- [investing-clarity-lab](https://github.com/Maureen-11/investing-clarity-lab)
- [between-us](https://github.com/Maureen-11/between-us)

它们是成员已有的项目经验，不会被原样包装成“走进照片”产品能力。

## 如何参与

如果你是队友：

1. 先阅读项目大纲和 `AGENTS.md`；
2. 把你的看法写到 `docs/feedback/YYYY-MM-DD-你的名字.md`；
3. 从自己的分支提交 Pull Request；
4. 不要直接覆盖共同大纲；不同意见先保留在反馈文件里；
5. 讨论确认后，再由共同维护者更新决策记录。

## 目前最重要的问题

我们还需要共同确认：

- “走进去”第一版必须包含哪些动作，才算真的有体验？
- 第一版使用哪一种技术路线，才能在 10 天内做出可演示版本？
- 哪些内容由成员 A 负责，哪些由成员 B 负责？
- 演示素材使用什么照片，如何获得授权？
- 比赛要求和评分标准的官方链接是什么？
