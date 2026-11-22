// Labels, units and times. Everything a person reads goes through here.

const UNITS = { degC: '°C', percent: '%', ppm: 'ppm', lux: 'lx', V: 'V', hPa: 'hPa' }
const QUANTITIES = {
  air_temperature: 'Air temperature',
  soil_temperature: 'Soil temperature',
  relative_humidity: 'Humidity',
  soil_moisture: 'Soil moisture',
  co2: 'CO₂',
  water_level: 'Reservoir',
  illuminance: 'Light',
  voltage: 'Voltage',
  pressure: 'Pressure',
}
const STATUSES = {
  ok: 'All good',
  idle: 'Empty',
  unknown: 'No status yet',
  needs_water: 'Needs water',
  too_wet: 'Too wet',
  reservoir_low: 'Reservoir low',
  too_cold: 'Too cold',
  too_hot: 'Too hot',
  too_dry: 'Air too dry',
  too_humid: 'Too humid',
  stale_air: 'Stale air',
  stage_ready: 'Ready for next stage',
  critical: 'Critical',
  sensor_stale: 'Sensor not reporting',
  offline: 'Node offline',
  paused: 'Paused',
}

export const unit = (code) => UNITS[code] ?? code ?? ''
export const quantityLabel = (q) => QUANTITIES[q] ?? sentence(q)
export const statusLabel = (s) => STATUSES[s] ?? sentence(s)

export function sentence(id) {
  const text = String(id ?? '').replace(/[_-]+/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function number(value, quantity) {
  if (value === null || value === undefined) return '–'
  const digits = quantity === 'co2' || quantity === 'illuminance' ? 0 : 1
  return Number(value).toFixed(digits)
}

export function reading(value, quantity, unitCode) {
  if (value === null || value === undefined) return 'no reading'
  const u = unit(unitCode)
  return `${number(value, quantity)}${u === '%' || u === '°C' ? '' : ' '}${u}`
}

/** "45 s", "12 min", "3 h", "2 d" */
export function span(seconds) {
  if (seconds === null || seconds === undefined) return '–'
  const s = Math.abs(seconds)
  if (s < 90) return `${Math.round(s)} s`
  if (s < 5400) return `${Math.round(s / 60)} min`
  if (s < 2 * 86400) return `${Math.round(s / 3600)} h`
  return `${Math.round(s / 86400)} d`
}

export const ago = (seconds) => (seconds === null || seconds === undefined ? 'never' : `${span(seconds)} ago`)

export function clock(iso, timeZone, withDate = false) {
  if (!iso) return '–'
  const options = { hour: '2-digit', minute: '2-digit', hour12: false, timeZone }
  if (withDate) Object.assign(options, { day: 'numeric', month: 'short' })
  try {
    return new Intl.DateTimeFormat(undefined, options).format(new Date(iso))
  } catch {
    return new Intl.DateTimeFormat(undefined, { ...options, timeZone: undefined }).format(new Date(iso))
  }
}
