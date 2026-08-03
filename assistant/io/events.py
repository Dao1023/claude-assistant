"""事件中枢:后端各处发生的事件,广播给所有 WebSocket 订阅者(浮窗、未来 AI)。

为什么要有它:弹窗层应是「被动响应」——通知层决定弹了,把结果推给弹窗;
弹窗不主动查询。WebSocket 就是这条「推」的通道。同时它是未来 AI 层的
「旁观事件流」总线:AI 订阅同一通道,实时看通知/完成/推迟发生。

跨线程桥:uvicorn 在子线程跑自己的 asyncio 循环;tick_push 在调度线程。
publish 从任意线程调用,经 loop.call_soon_threadsafe 转给 uvicorn 的循环去广播,
线程安全。事件是普通 dict:{type, ts, ...payload},JSON 可序列化。

两种订阅者:
- WebSocket 订阅者(浮窗、外部):跨进程/跨网络,走 /ws 广播。
- 本地订阅者(AI Agent):同进程,经 subscribe_local 注册回调,publish 时同步直调,
  零网络开销。回调在 publish 方线程里跑,务必只丢 queue 别干重活。

属于 io 层:只管「把事件送达订阅者」,不含业务判断。
"""
import asyncio
import json
import threading

from ..core.timeutil import now_ts

_clients = set()          # 已连接的 WebSocket(fastapi.WebSocket)
_local_subs = []          # 本地订阅回调 fn(event: dict),同进程直调(如 AI Agent)
_loop = None              # uvicorn 的 asyncio 循环(在 /ws 首次连接时捕获)
_lock = threading.Lock()


def subscribe_local(fn):
    """注册本地订阅者(AI Agent):publish 时同步调 fn(event)。

    fn 在 publish 方线程里被调,必须轻(只丢 queue),重活放自己的线程。
    """
    with _lock:
        _local_subs.append(fn)


def unsubscribe_local(fn):
    with _lock:
        if fn in _local_subs:
            _local_subs.remove(fn)


def _set_loop(loop):
    global _loop
    with _lock:
        _loop = loop


async def register(ws):
    """/ws 端点调用:接受连接并登记。返回后由端点持有,断开时调 unregister。"""
    await ws.accept()
    _set_loop(asyncio.get_running_loop())
    with _lock:
        _clients.add(ws)


def unregister(ws):
    with _lock:
        _clients.discard(ws)


async def _broadcast(message):
    """在 uvicorn 循环里跑:把消息发给所有订阅者,静默剔除已断开的。"""
    dead = []
    with _lock:
        targets = list(_clients)
    for ws in targets:
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        unregister(ws)


def publish(event_type, **payload):
    """从任意线程发布一个事件。先送达本地订阅者,再广播 WS 订阅者。

    本地订阅者与 WS 解耦:即便没有浮窗在线(Agent 仍要旁观),本地订阅也照收。
    """
    event = {"type": event_type, "ts": now_ts(), **payload}

    # 本地订阅者(AI Agent):同步直调,回调须轻(丢 queue)。异常不拖垮发布方。
    with _lock:
        subs = list(_local_subs)
    for fn in subs:
        try:
            fn(event)
        except Exception:
            pass

    # WS 订阅者(浮窗):无循环/无客户端时跳过。
    with _lock:
        loop = _loop
        has_clients = bool(_clients)
    if loop is None or not has_clients:
        return
    message = json.dumps(event, ensure_ascii=False)
    loop.call_soon_threadsafe(lambda: asyncio.ensure_future(_broadcast(message)))
