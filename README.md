# Claude Assistant(常驻主动提醒助理)

> 一个常驻 Windows 托盘的小程序,是 Claude Code 的**外部助手/代理人**(哑终端,不思考)。
> Claude Code 是大脑,它是手脚:盯着 Claude Code 下发的指令、到点弹窗提醒、一键唤起 Claude Code。

## 为什么做这个

- 和 Claude Code 对话能产生动力、理清思路,但窗口一关(它本质就是个 terminal/powershell),一切归零,之后很久想不起打开。
- 需要一个**主动**的常驻助手:Claude Code 不在时,它替 Claude Code 把提醒推到我面前,并能一键把我拉回对话。
- 定位:**助手,不是替代**。思考、记忆、对话全在 Claude Code;APP 只负责"盯信箱 + 弹窗 + 唤起"。

## 核心功能(最小原型 V1)

1. **盯信箱**:监听信箱文件,发现 Claude Code 写入的新指令就读取。
2. **到点弹窗**:按指令里的时间,弹系统通知提醒我。
3. **唤起 Claude Code**:通知带"和 Claude 聊聊"入口,点了打开 Claude Code 并自动带一句话,接续对话。
4. **回写状态**:把"已读/已点/已完成"写回信箱,供 Claude Code 随时查询。

## 架构与分工

```
┌──────────────┐   ① 写指令到信箱(inbox.json)   ┌──────────────┐
│  Claude Code │ ───────────────────────────────→ │  信箱文件     │
│   (大脑)     │                                   │ inbox.json   │
│              │ ←─────────────────────────────── │              │
└──────────────┘   ④ 读状态(APP 回写)             └──────┬───────┘
       ↑                                                  │ ② 监听
       │ ③ 唤起(带开场白)                                ↓
       │                                          ┌──────────────┐
       └──────────────────────────────────────────│  常驻 APP    │
              (子进程打开 claude code)              │  (哑终端)    │
                                                  └──────┬───────┘
                                                         │ 到点弹窗
                                                         ↓
                                                      提醒我
```

- **通信协议 = 信箱 JSON 文件**。这是唯一的接口契约,APP 用什么实现都行,Claude Code 只认文件。
- 后续可加 HTTP(Claude Code 直接 POST 给 APP),V1 先用文件监听,最简单可靠。

## 信箱协议(inbox.json)

```json
{
  "reminders": [
    {
      "id": "uuid",
      "time": "2026-07-28 09:00",
      "msg": "开虚拟机,昨天说好的",
      "status": "pending",
      "created_by": "claude",
      "note": ""
    }
  ]
}
```

- `status`: `pending`(待发)→ `notified`(已弹窗)→ `done`(已完成)/ `dismissed`(已忽略)
- APP 监听文件新增/变更 → 到点弹窗 → 用户操作后回写 `status` 和 `note`
- Claude Code 读这个文件即可知道每条提醒的状态

## 技术选型(V1)

- **Python 3.13**(机器已有),快速出原型
- `watchdog` —— 监听信箱文件变更
- `win10toast` 或 `windows-toasts` —— 系统通知弹窗
- `pystray` —— 系统托盘常驻
- 唤起:`subprocess` 启动 `claude`(可带 prompt 参数)

## 目录规划

```
claude-assistant/
├── README.md           ← 本文件(规划)
├── inbox.json          ← 信箱(Claude Code 与 APP 的接口)
├── assistant/
│   ├── main.py         ← 入口,常驻+托盘
│   ├── watcher.py      ← 监听信箱
│   ├── notifier.py     ← 弹窗
│   └── launcher.py     ← 唤起 Claude Code
└── requirements.txt
```

## 开发步骤(V1)

1. [ ] 定义并写死 `inbox.json` 的 schema,放一条示例提醒
2. [ ] `watcher.py`:watchdog 监听 inbox.json,加载 pending 提醒
3. [ ] `notifier.py`:到点弹系统通知
4. [ ] `launcher.py`:通知点击后唤起 claude code 并带开场白
5. [ ] 回写 status 到 inbox.json
6. [ ] `main.py`:串起来 + pystray 托盘常驻
7. [ ] Claude Code 侧:约定一套"我往 inbox.json 写提醒"的操作方式

## 后续版本(V2+ 再谈)

- HTTP 服务(Claude Code 直接 POST,不用等文件监听)
- 托盘菜单:查看待办、暂停提醒、手动唤起
- 定时对账:每天固定时间主动汇总 Daily / 翻出被遗忘的事
- 体验升级:若觉得 Python 原型太简陋,换 Electron / C# 重写
