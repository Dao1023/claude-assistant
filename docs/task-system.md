# 任务系统

## 两种任务类型:重要性增长模型

市面上的日程软件是"静态"的,只擅长处理 deadline。但很多事没有 deadline,重要性却随时间增长。需要同时支持两种:

### 1. deadline 任务(指数增长)
有明确截止时间。越接近截止,越紧急。
- 例:报销、论文投稿、报价单。
- 重要性模型:**指数增长**,逼近 deadline 时急剧升高。

### 2. start-time 任务(对数增长)
没有 deadline,但"越拖越该做"。
- 例:"朋友很久没联系了""PLC 环境一直没搭"。
- 重要性模型:**对数增长**,起步平缓、持续缓慢上升,不会"爆炸",但一直在涨。

> 对数增长需要一个**时间锚点**:"上次完成 / 上次提及"是什么时候。没有锚点就算不出"久到什么程度"。因此每个任务必须记录 `last_done`(上次完成时间)或 `created`(创建时间)作为计算起点。

## 任务数据模型

```json
{
  "id": "uuid",
  "title": "给张工发 YFPO 测试视频",
  "type": "deadline",
  "created": "2026-07-27 10:00",
  "deadline": "2026-07-30 18:00",
  "last_done": null,
  "priority": 3,
  "status": "pending",
  "nag_count": 0,
  "last_nagged": null,
  "note": ""
}
```

| 字段 | 含义 |
|---|---|
| `id` | 唯一标识 |
| `title` | 任务内容(显示在通知里) |
| `type` | `deadline` 或 `start-time` |
| `created` | 创建时间(start-time 任务的默认锚点) |
| `deadline` | 截止时间(仅 deadline 任务) |
| `last_done` | 上次完成时间(start-time 任务的锚点,做完后更新) |
| `priority` | 用户主观优先级(1-5),与模型算出的客观重要度加权 |
| `status` | `pending` / `done` / `snoozed` / `dismissed` |
| `nag_count` | 已被催次数(用于升级判断) |
| `last_nagged` | 上次催促时间(用于间隔控制) |
| `note` | 备注 / 用户反馈 |

## 增删改查

由 APP 提供,Claude Code 通过 inbox.json 下指令触发,或未来提供 HTTP/CLI:

- **增**:用户说"最近要搞 XX" → Claude Code 解析 → 写 inbox 指令 → APP 建任务。
- **删**:用户说"XX 做完了" → APP 标记 `done`,deadline 任务归档;start-time 任务更新 `last_done` 并重新计时。
- **改**:用户说"记错了" → APP 更新字段。
- **查**:用户问"最近有啥要紧事" → APP 按重要度筛选排序返回。**这是 APP 的主场:毫秒级、零遗漏筛选,不占用模型上下文。**

## 重要度计算(排序依据)

```
当前重要度 = f(类型增长模型, 时间锚点) × priority 权重
```

- deadline 任务:距截止越近,值越大(指数)。
- start-time 任务:距锚点越久,值越大(对数)。

APP 定时对所有 `pending` 任务算一遍当前重要度,排序,决定"现在最该催谁"。具体公式参数待定,先定性,体验后再调。
