/**
 * 通知提示音:Web Audio 现场合成,不依赖任何音频文件。
 *
 * 浮窗常驻(hidden 不销毁),页面早已加载;notify 事件到达时浏览器
 * 自动播放限制早已解除(有过用户交互/页面驻留),可直接发声。
 * 双音上行小提示,短、干净、不刺耳;受设置 notify_sound 开关管。
 */
import { fetchRules } from '@/api/client'

let ctx: AudioContext | null = null

function getCtx(): AudioContext | null {
  try {
    if (!ctx) {
      const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
      if (!AC) return null
      ctx = new AC()
    }
    if (ctx.state === 'suspended') void ctx.resume()
    return ctx
  } catch {
    return null
  }
}

/** 一个音符:正弦 + 指数衰减包络,避免爆音。peak 为峰值增益(0-1)。 */
function tone(ac: AudioContext, freq: number, at: number, dur: number, peak: number) {
  const osc = ac.createOscillator()
  const gain = ac.createGain()
  osc.type = 'sine'
  osc.frequency.value = freq
  gain.gain.setValueAtTime(0.0001, at)
  gain.gain.exponentialRampToValueAtTime(Math.max(peak, 0.0001), at + 0.015)  // 快起音
  gain.gain.exponentialRampToValueAtTime(0.0001, at + dur)                     // 缓释
  osc.connect(gain)
  gain.connect(ac.destination)
  osc.start(at)
  osc.stop(at + dur + 0.05)
}

/** 播一段提示音(双音上行)。notify_sound 关则静默;音量按 notify_volume(0-100)。 */
export async function playNotifySound() {
  let volume = 1.0                                   // 满幅 = 浏览器不削波的最大音量
  try {
    const r = await fetchRules()
    const get = (k: string) => r.editable.find((s) => s.key === k)?.value
    if (get('notify_sound') === 0) return
    const v = get('notify_volume')
    if (v != null) volume = Math.min(Math.max(v, 0), 100) / 100
  } catch { /* 拉不到设置就按默认满幅 */ }
  if (volume <= 0) return
  const ac = getCtx()
  if (!ac) return
  const t = ac.currentTime
  tone(ac, 880, t, 0.22, volume)          // A5
  tone(ac, 1318.5, t + 0.13, 0.34, volume) // E6,错开半拍上行
}
