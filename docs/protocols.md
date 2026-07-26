# 文件协议

APP 与 Claude Code 通过文件通信。两个文件分开:**inbox.json 是"指令通道",tasks.json 是"任务库"**。

## inbox.json —— 指令通道(Claude Code → APP)

Claude Code 把用户的自然语言翻译成结构化指令写到这里,APP 监听并执行。

```json
{
  "commands": [
    {
      "id": "uuid",
      "action": "add",
      "payload": {
        "title": "给张工发 YFPO 测试视频",
        "type": "deadline",
        "deadline": "2026-07-30 18:00",
        "priority": 3
      },
      "status": "pending",
      "created": "2026-07-27 10:00"
    }
  ]
}
```

- `action`: `add` / `done` / `update` / `dismiss` / `snooze` / `query`
- `status`: APP 处理后改为 `processed`,并回写结果(如 query 的答案)
- 兼容 V1:纯粹的"到点弹一句话"提醒,可作为 `action: "remind"` 保留

## tasks.json —— 任务库(APP 权威数据源)

由 APP 持有和维护,结构见 [task-system.md](task-system.md) 的任务数据模型。Claude Code 只读(用于查询/汇报),不直接改。

## 职责与流向

```
用户自然语言
   │ (对话)
   ▼
Claude Code 理解 → 写 inbox.json(指令)
                        │ APP 监听解析
                        ▼
                  维护 tasks.json(增删改)
                        │ APP 生命周期引擎定时算
                        ▼
                  弹通知催用户(三档强度)
                        │ 用户处理后
                        ▼
                  回写状态(done/snoozed/dismissed)
```

## 默认配置(待定参数先填默认值)

```json
{
  "nag": {
    "max_concurrent": 3,
    "gentle_interval_hours": [1, 3],
    "crisis_burst_count": 5,
    "escalate_after_nags": 3
  }
}
```

> 这些默认值是占位,用户体验一段时间后调整(见 lifecycle.md "待拍板参数")。
