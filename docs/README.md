# Claude Assistant 设计文档

这里记录 claude-assistant 的设计演进。V1 是一个"到点弹窗"的最小哑终端;V2 起,根据用户的真实需求,APP 将承担更多**确定性、批处理**的职责。

## 文档导航

| 文档 | 内容 |
|---|---|
| [requirements.md](requirements.md) | **需求**(用户的原始思考,收敛后):任务两类驱动、log 重要性算法、tag、推送层独立 |
| [architecture.md](architecture.md) | 整体架构,APP 与 Claude Code 的职责边界,双驱动任务模型概览 |
| [task-system.md](task-system.md) | 任务系统:start/end 双驱动、周期修饰符、log 重要性算法、任务核心属性 |
| [lifecycle.md](lifecycle.md) | 推送生命周期(挂在任务上)+ 三档催促 + 防过载节流 |
| [storage.md](storage.md) | 存储选型:为什么 JSON → SQLite,与 Claude Code 的通信方式 |
| [agent.md](agent.md) | **AI Agent(第四层)**:现状、敷衍问题诊断、五层重构蓝图、工程要点、Roadmap |

> 阅读顺序:requirements(想做什么)→ architecture(怎么分工)→ task-system / lifecycle(两块核心)→ storage(数据怎么存)→ agent(AI 层)。
>
> 外部设计参考(非本系统设计)在 [reference/](reference/);superpowers 工具的过程产物在 superpowers/。

## 为什么从 V1 升级到 V2

V1(tag v0.1.0)验证了核心闭环:盯信箱 → 弹窗 → 唤起 claude → 回写状态。但暴露出两个根本局限:

1. **提醒没有生命周期**。V1 是"弹一下就完事"。弹了你没看到、看到了想歇会再看、点掉了没真做——都石沉大海。真实场景需要"任务不解决就一直追,且有节奏、有强度变化"。

2. **增删改查不该由 Claude Code 承担**。任务一多(亲朋好友联系频率 + 公司杂事 + 各种),每次对话都要把全量任务读进上下文,慢、易漏、易记串。筛选"3 天没联系的人""本周到期的事"这类操作,是程序毫秒级、零遗漏、可复用的事,该 APP 干,不该靠概率的模型干。

因此 V2 的核心转变:**APP 从"哑终端"升级为"持有任务系统、跑任务生命周期"的常驻服务**;Claude Code 退回到"理解自然语言、做决策、与用户对话"的大脑角色。

## 用户的核心诉求(设计锚点)

> "我需要一个 AI 助手。我平时很忙,不一定能照顾到方方面面,有它我就不需要总想着哪里没做好了,这样自己无拘无束。"
> —— 用户 2025-04 的设想(见 vault `Markdown/My/AI日程助理.md`)

核心价值不是"提醒",而是**卸下"总想着哪里没做好"的心理负担**。所有设计都应服务于这一点:让用户敢忘,因为知道 APP 会追到底。
