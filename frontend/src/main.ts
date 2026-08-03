import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import NotifyPage from './components/NotifyPage.vue'
import './main.css'

// 无 vue-router,按路径选根组件:
// /notify → 通知浮窗(pywebview 壳的内容);其余 → 任务面板。
const isNotify = window.location.pathname.startsWith('/notify')
const app = createApp(isNotify ? NotifyPage : App)

app.use(createPinia())
// Element Plus 组件与样式由 unplugin 按需自动引入,无需 app.use(ElementPlus)

app.mount('#app')
