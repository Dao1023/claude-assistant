# 数字生命 · 设计文档

> V4.1。daemon（心跳/计时器/意识层/数据后端，永不睡）+ Agent 大脑（跑在 harness，可换）。
> V1–V3 的历史文档已清理，git 历史可查；仍在用的工程教训蒸馏在 [lessons.md](lessons.md)。

## 文档导航

| 文档 | 内容 |
|---|---|
| [architecture.excalidraw](architecture.excalidraw) | **V4.1 组成架构**（活的协作画布：Excalidraw 打开直接编辑；节律四态独立于此图） |
| [rhythm.md](rhythm.md) | **节律四态**：休眠/睡眠/待机/工作；唤醒经济学；换档防抖；开放问题 |
| [task-system.md](task-system.md) | **双驱动任务模型**（核心 IP）：start 越久没做越重要 `log(间隔/周期)`、end 越近截止越急 `-log(剩余)`、周期修饰符 |
| [schema.md](schema.md) | **档案规范**：SQLite 表结构 + REST 接口（数据后端的规范；「模块落位」一节是 V2 遗留，待修） |
| [lessons.md](lessons.md) | **工程教训**：prompt 分层吃缓存、判定协议（沉默是判定）、记忆即攻击面 |

## 设计锚点（不变）

> "我需要一个 AI 助手。我平时很忙,不一定能照顾到方方面面,有它我就不需要总想着哪里没做好了,这样自己无拘无束。"
> —— 用户 2025-04 的设想

核心价值不是"提醒"，而是**卸下"总想着哪里没做好"的心理负担**。所有设计都应服务于这一点：
让用户敢忘，因为知道它会追到底。

## 已退役（git 历史可查）

V2 四层架构（architecture.md）、推送生命周期与三档催促（lifecycle.md）、存储选型论证（storage.md）、
AI 旁观层设计与五层重构（agent.md → 蒸馏为 lessons.md）、V3 演进文档（architecture-v3.md/.html）。
退役原因：V4.1 中②通知层、③浮窗、daemon 内 AI 层全部退役，提醒改由「大脑 + 计时器」驱动。
