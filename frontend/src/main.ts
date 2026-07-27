import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import './main.css'

const app = createApp(App)

app.use(createPinia())
// Element Plus 组件与样式由 unplugin 按需自动引入,无需 app.use(ElementPlus)

app.mount('#app')
