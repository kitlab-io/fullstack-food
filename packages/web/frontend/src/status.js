// Turns the site's LED theme into what the screen shows, so a card matches its LED segment.
import { site } from './api.js'

/** [R, G, B, W] as driven on the strip -> a CSS colour readable on screen. */
export function ledColor(rgbw) {
  if (!rgbw) return 'var(--muted)'
  const [r, g, b, w = 0] = rgbw
  const mixed = [r + w, g + w, b + w].map((c) => Math.min(255, c))
  const peak = Math.max(...mixed)
  if (peak < 8) return 'var(--muted)'            // LEDs off: show a neutral dot, not black
  const scale = 225 / peak                       // LED levels are dim on purpose; screens need more
  const [R, G, B] = mixed.map((c) => Math.round(c * scale))
  return `rgb(${R} ${G} ${B})`
}

export function statusStyle(status) {
  const theme = site.value?.theme.statuses ?? {}
  const style = theme[status] ?? (status === 'unknown' ? null : theme.critical)
  return { color: ledColor(style?.color), effect: style?.effect ?? 'solid' }
}

// Statuses that wait for a person. They get a banner on the overview.
export const NEEDS_PERSON = {
  stage_ready: 'Ready to move to the next stage.',
  reservoir_low: 'Refill the reservoir: watering is blocked until it is.',
  offline: 'A node is offline: nothing in this zone can be switched.',
  sensor_stale: 'A sensor has stopped reporting: loops that depend on it are held off.',
  critical: 'A reading is far outside what this planting tolerates.',
  paused: 'Paused: everything is off until the zone is resumed.',
  observing: 'Observe mode: decisions are logged but nothing is switched.',
}

// 24x24 stroke icons. Colour is never the only signal: every status has its own shape.
const ICONS = {
  check: 'M5 12.5l4.5 4.5L19 7.5',
  drop: 'M12 3.5c3.2 3.9 5.5 6.8 5.5 9.8a5.5 5.5 0 0 1-11 0c0-3 2.3-5.9 5.5-9.8z',
  drops: 'M8 4c2 2.5 3.5 4.3 3.5 6.2a3.5 3.5 0 0 1-7 0C4.500 8.3 6 6.500 8 4zM16.500 11c1.700 2.100 3 3.700 3 5.300a3 3 0 0 1-6 0c0-1.600 1.300-3.200 3-5.300z',
  bucket: 'M5 8h14l-1.500 11h-11zM4 8h16M9 13h6',
  cold: 'M12 3v18M4.200 7.500l15.600 9M19.800 7.500l-15.600 9',
  hot: 'M10 14.500V5a2 2 0 0 1 4 0v9.500a4 4 0 1 1-4 0zM12 9v8',
  sun: 'M12 8a4 4 0 1 0 0 8a4 4 0 0 0 0-8zM12 2.500v2.500M12 19v2.500M2.500 12h2.500M19 12h2.500M5.300 5.300l1.800 1.800M16.900 16.900l1.800 1.800M5.300 18.700l1.800-1.800M16.900 7.100l1.800-1.800',
  cloud: 'M7 18.500a4 4 0 0 1-.500-7.970 5.500 5.500 0 0 1 10.700 1.270A3.400 3.400 0 0 1 17 18.500z',
  wind: 'M3 9h10.500a2.500 2.500 0 1 0-2.500-2.500M3 14h15a2.500 2.500 0 1 1-2.500 2.500M3 11.500h6',
  flag: 'M6 21V4M6 4.500h11l-2.500 4 2.500 4H6',
  alert: 'M12 4l9 15.500H3zM12 10v4.500M12 17.200v.300',
  silent: 'M4 4l16 16M8.500 8.500a5 5 0 0 0 7 7M12 3v2M12 19v2M3 12h2M19 12h2M12 9.500a2.500 2.500 0 0 1 2.500 2.500',
  offline: 'M4 4l16 16M2.500 9.500a14 14 0 0 1 4.600-3M9.500 6.200A14 14 0 0 1 21.500 9.500M6 13a9 9 0 0 1 3.500-2.300M14.800 11a9 9 0 0 1 3.200 2M9.500 16.500a4 4 0 0 1 5 0M12 20v.300',
  pause: 'M8.500 5v14M15.500 5v14',
  empty: 'M12 4a8 8 0 1 0 0 16a8 8 0 0 0 0-16z',
  eye: 'M2.500 12s3.500-6.500 9.500-6.500S21.500 12 21.500 12s-3.500 6.500-9.500 6.500S2.500 12 2.500 12zM12 9.500a2.500 2.500 0 1 0 0 5a2.500 2.500 0 0 0 0-5z',
  question: 'M9.200 9a2.900 2.900 0 1 1 4.300 2.500c-.900.500-1.500 1.100-1.500 2.300M12 17.200v.300',
}
const STATUS_ICON = {
  ok: 'check', idle: 'empty', unknown: 'question', needs_water: 'drop', too_wet: 'drops',
  reservoir_low: 'bucket', too_cold: 'cold', too_hot: 'hot', too_dry: 'sun', too_humid: 'cloud',
  stale_air: 'wind', stage_ready: 'flag', critical: 'alert', sensor_stale: 'silent',
  offline: 'offline', paused: 'pause', observing: 'eye',
}
export const iconPath = (status) => ICONS[STATUS_ICON[status] ?? 'alert']
