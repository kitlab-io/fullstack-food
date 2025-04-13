<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import axios from 'axios';
import LineChart from './LineChart.vue';
import { Timeline } from 'vue-timeline-chart';
import 'vue-timeline-chart/style.css';

// State management
const temperatureData = ref([]);
const loading = ref(false);
const error = ref(null);
const selectedSensorType = ref('soil_temp');
const timeRange = ref(7); // Default to 7 days

// Sensor type options
const sensorTypes = [
  { value: 'soil_temp', label: 'Soil Temperature' },
  { value: 'air_temp_humidity', label: 'Air Temperature' },
  { value: 'air_temp_humidity_barometer', label: 'Barometric Temperature' }
];

// Colors for different sensor types
const sensorColors = {
  'soil_temp': '#ff7f0e',  // Orange
  'air_temp_humidity': '#1f77b4',  // Blue
  'air_temp_humidity_barometer': '#2ca02c'  // Green
};

// Time range options
const timeRangeOptions = [
  { value: 1, label: 'Last 24 Hours' },
  { value: 7, label: 'Last 7 Days' },
  { value: 30, label: 'Last 30 Days' }
];

// Computed values for chart
const chartTitle = computed(() => {
  const sensorLabel = sensorTypes.find(t => t.value === selectedSensorType.value)?.label || 'Temperature';
  return `${sensorLabel} Readings - Last ${timeRange.value} ${timeRange.value === 1 ? 'Day' : 'Days'}`;
});

const chartColor = computed(() => {
  return sensorColors[selectedSensorType.value] || '#ff7f0e';
});

// Fetch data from API
async function fetchTemperatureData() {
  loading.value = true;
  error.value = null;
  
  try {
    const response = await axios.get('/api/sensor-data', {
      params: {
        type: selectedSensorType.value,
        days: timeRange.value
      }
    });
    
    if (response.data.status === 'success') {
      temperatureData.value = response.data.data;
    } else {
      throw new Error(response.data.message || 'Failed to fetch data');
    }
  } catch (err) {
    error.value = err.message || 'An error occurred while fetching data';
    console.error('Error fetching temperature data:', err);
  } finally {
    loading.value = false;
  }
}

// Handle sensor type change
function changeSensorType(event) {
  selectedSensorType.value = event.target.value;
  fetchTemperatureData();
}

// Handle time range change
function changeTimeRange(event) {
  timeRange.value = parseInt(event.target.value, 10);
  fetchTemperatureData();
}

// Timeline data (keep for example)
const timelineGroups = [
  { id: 'temp', label: 'Temperature' },
  { id: 'light', label: 'Light Schedule' },
  { id: 'water', label: 'Watering' }
];

// Create items for the timeline based on temperature data
const timelineItems = computed(() => {
  if (!temperatureData.value || temperatureData.value.length === 0) return [];
  
  // Calculate average to determine high/low temperature events
  const values = temperatureData.value.map(d => d.value);
  const avg = values.reduce((a, b) => a + b, 0) / values.length;
  const threshold = avg * 1.1; // 10% above average
  
  return temperatureData.value
    .filter(d => d.value > threshold) // Filter for high temperature events
    .map(d => ({
      group: 'temp',
      type: 'point',
      start: d.timestamp,
      cssVariables: { '--item-background': chartColor.value }
    }));
});

// Calculate the visible time range
const visibleTimeRange = computed(() => {
  const now = new Date();
  const start = new Date();
  start.setDate(start.getDate() - timeRange.value);
  
  return {
    start: start.getTime(),
    end: now.getTime()
  };
});

// Fetch data on component mount
onMounted(() => {
  fetchTemperatureData();
});
</script>

<template>
  <div class="sensor-data-container">
    <h2>Sensor Data Visualization</h2>
    
    <!-- Controls section -->
    <div class="controls">
      <div class="control-group">
        <label for="sensor-type">Sensor Type:</label>
        <select id="sensor-type" v-model="selectedSensorType" @change="changeSensorType">
          <option v-for="option in sensorTypes" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </div>
      
      <div class="control-group">
        <label for="time-range">Time Range:</label>
        <select id="time-range" v-model="timeRange" @change="changeTimeRange">
          <option v-for="option in timeRangeOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </div>
    </div>
    
    <!-- Temperature Chart -->
    <div class="chart-wrapper">
      <div v-if="loading" class="loading-overlay">
        <div class="spinner"></div>
        <p>Loading sensor data...</p>
      </div>
      
      <div v-if="error" class="error-message">
        <p>{{ error }}</p>
        <button @click="fetchTemperatureData">Try Again</button>
      </div>
      
      <div v-if="!loading && !error && temperatureData.length === 0" class="no-data">
        <p>No temperature data available for the selected time range.</p>
      </div>
      
      <div v-if="!loading && !error && temperatureData.length > 0" class="chart-container">
        <LineChart 
          :data="temperatureData"
          :title="chartTitle"
          :color="chartColor"
          :timeRange="visibleTimeRange"
          :yAxisLabel="'Temperature (°C)'"
          :height="400"
        />
      </div>
    </div>
    
    <!-- Timeline section (shows activities alongside temperature data) -->
    <div class="timeline-section" v-if="temperatureData.length > 0">
      <h3>System Activity Timeline</h3>
      <p class="timeline-description">
        This timeline shows temperature events and system activities
      </p>
      
      <timeline 
        :groups="timelineGroups" 
        :items="timelineItems" 
        :viewportMin="visibleTimeRange.start" 
        :viewportMax="visibleTimeRange.end"
      />
    </div>
  </div>
</template>

<style lang="scss" scoped>
.sensor-data-container {
  padding: 20px;
  background-color: #f9f9f9;
  border-radius: 8px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
  
  h2 {
    margin-top: 0;
    margin-bottom: 20px;
    color: #333;
  }
  
  h3 {
    margin-top: 30px;
    margin-bottom: 10px;
    color: #333;
  }
}

.controls {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  margin-bottom: 30px;
  
  .control-group {
    display: flex;
    flex-direction: column;
    
    label {
      margin-bottom: 5px;
      font-weight: 600;
    }
    
    select {
      padding: 8px 12px;
      border: 1px solid #ccc;
      border-radius: 4px;
      background-color: white;
      font-size: 14px;
      min-width: 200px;
      
      &:focus {
        outline: none;
        border-color: #66afe9;
        box-shadow: 0 0 5px rgba(102, 175, 233, 0.5);
      }
    }
  }
}

.chart-wrapper {
  position: relative;
  background: white;
  border-radius: 6px;
  box-shadow: 0 1px 5px rgba(0, 0, 0, 0.1);
  padding: 15px;
  min-height: 400px;
}

.loading-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(255, 255, 255, 0.8);
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  z-index: 5;
  
  .spinner {
    width: 40px;
    height: 40px;
    border: 3px solid rgba(0, 0, 0, 0.1);
    border-radius: 50%;
    border-top-color: #3498db;
    animation: spin 1s ease-in-out infinite;
    margin-bottom: 10px;
  }
  
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
}

.error-message {
  padding: 20px;
  background-color: #fee;
  border-left: 4px solid #e74c3c;
  margin: 20px 0;
  
  button {
    background-color: #3498db;
    color: white;
    border: none;
    padding: 8px 16px;
    border-radius: 4px;
    cursor: pointer;
    
    &:hover {
      background-color: #2980b9;
    }
  }
}

.no-data {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 300px;
  background-color: #f9f9f9;
  border: 1px dashed #ccc;
  border-radius: 4px;
  
  p {
    color: #777;
    font-style: italic;
  }
}

.chart-container {
  height: 400px;
}

.timeline-section {
  margin-top: 40px;
  
  .timeline-description {
    color: #666;
    margin-bottom: 20px;
  }
}
</style>