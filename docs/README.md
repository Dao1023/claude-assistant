# 数字生命 · 设计文档

> V4.2。**社区组装 + 唯一自建插件**:dsh-desktop 常驻守夜 · dsh-cron 闹钟 · dsh-task-brain 插件(自建) ·
> dsh-im 微信触达 · dsh-mnemon 记忆 · SQLite 双驱动档案(核心 IP)。
> 演进史(V1 哑终端 → V2 常驻服务 → V4 daemon → V4.2 社区组装)见 git 历史与各文档"退役"注记。

## 文档导航

| 文档 | 内容 |
|---|---|
| [community-survey.md](community-survey.md) | **V4.2 方案与选型**:六路社区调查、组装清单、七阶段施工路线图、风险清单 |
| [architecture.excalidraw](architecture.excalidraw) | **V4.2 组成架构**(活画布:Excalidraw 编辑;🔵社区 🟢自建 ⭐核心IP 🟠退役) |
| [rhythm.md](rhythm.md) | **节律四态**(V4.2 语义:四态=cron 任务密度)+ 唤醒经济学 + 磨合机制 + 设计宪法 |
| [task-system.md](task-system.md) | **双驱动任务模型**(核心 IP):start `log(间隔/周期)` / end `-log(剩余)` / 周期克隆 |
| [schema.md](schema.md) | **档案规范**:SQLite 表结构 + 动作语义(V4.2:外壳=插件工具,表结构不变) |
| [lessons.md](lessons.md) | **工程教训**:prompt 分层吃缓存、判定协议(沉默是判定)、记忆即攻击面 |

## 设计锚点(两句话,2025-04 至今不变)

> "我需要一个 AI 助手。我平时很忙,不一定能照顾到方方面面,有它我就不需要总想着
> 哪里没做好了,这样自己无拘无束。" —— 用户 2025-04

核心价值不是"提醒",而是**卸下"总想着哪里没做好"的心理负担**:让用户敢忘,因为知道她会追到底。

## 设计宪法(三次架构翻转零改动的原则)

1. **闹钟就是闹钟,女仆才是决策者**——计时器只管到点响;看时间、看主人、看环境、
   决定说不说、重排下一个闹钟,全是女仆(大脑)醒来后的事。闹钟永不为场景扩功能。
2. **先定基本方向,未来慢慢调整**——反过度设计;人格与提醒节奏靠长期磨合
   (shadow mode / 作息先验 / 任务驱动的人格变量),不靠一次性把功能做全。

## 已退役(细节见 git 历史)

V2 四层架构与 funnel 三档催促(提醒改由"大脑+cron"驱动)、pywebview 浮窗、旧 daemon
(timers.py/consciousness.py → 实验资产)、REST 服务面与 Vue 面板(V4.2 起不维护)。
