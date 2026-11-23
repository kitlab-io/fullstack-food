import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'

import App from './App.vue'
import Devices from './views/Devices.vue'
import Help from './views/Help.vue'
import Log from './views/Log.vue'
import Overview from './views/Overview.vue'
import Raw from './views/Raw.vue'
import Simulator from './views/Simulator.vue'
import ZoneDetail from './views/ZoneDetail.vue'
import 'uplot/dist/uPlot.min.css'
import './style.css'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: Overview },
    { path: '/zones/:id', component: ZoneDetail, props: true },
    { path: '/devices', component: Devices },
    { path: '/log', component: Log },
    { path: '/raw', component: Raw },
    { path: '/simulator', component: Simulator },
    { path: '/help', component: Help },
    { path: '/help/:status', component: Help, props: true },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

createApp(App).use(router).mount('#app')
