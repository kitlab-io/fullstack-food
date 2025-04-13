import { createRouter, createWebHistory } from 'vue-router'
import Books from '../components/Books.vue'
import Ping from '../components/Ping.vue'
import Sensors from '../components/SensorData.vue'
import PhotoGallery from '../components/PhotoGallery.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'Sensor Data',
      component: Sensors,
    },
    {
      path: '/photos',
      name: 'Photo Gallery',
      component: PhotoGallery,
    },
    {
      path: '/books',
      name: 'Books',
      component: Books,
    },
    {
      path: '/ping',
      name: 'ping',
      component: Ping
    },
  ]
})

export default router
