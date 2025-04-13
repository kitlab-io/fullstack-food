<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue';
import axios from 'axios';
import { Timeline } from 'vue-timeline-chart';
import 'vue-timeline-chart/style.css';

// State management
const photos = ref([]);
const loading = ref(false);
const error = ref(null);
const selectedSpecies = ref('');
const selectedLocation = ref('');
const timeRange = ref(30); // Default to 30 days
const filterOptions = ref({
  species: [],
  locations: []
});
const zoomedPhoto = ref(null);
const showLightbox = ref(false);

// Time range options
const timeRangeOptions = [
  { value: 1, label: 'Last 24 Hours' },
  { value: 7, label: 'Last 7 Days' },
  { value: 30, label: 'Last 30 Days' },
  { value: 90, label: 'Last 3 Months' },
  { value: 365, label: 'Last Year' }
];

// API base URL
const baseUrlApi = "http://localhost:5001";

// Format photo date for display
const formatDate = (timestamp) => {
  const date = new Date(timestamp);
  return date.toLocaleString();
};

// Fetch photos from API
async function fetchPhotos() {
  loading.value = true;
  error.value = null;

  try {
    const response = await axios.get(baseUrlApi + '/api/photos', {
      params: {
        days: timeRange.value,
        species: selectedSpecies.value || undefined,
        location: selectedLocation.value || undefined
      }
    });

    if (response.data.status === 'success') {
      photos.value = response.data.photos;
      filterOptions.value = response.data.filter_options;
    } else {
      throw new Error(response.data.message || 'Failed to fetch photos');
    }
  } catch (err) {
    error.value = err.message || 'An error occurred while fetching photos';
    console.error('Error fetching photos:', err);
  } finally {
    loading.value = false;
  }
}

// Timeline items - convert photos to timeline format
const timelineItems = computed(() => {
  return photos.value.map(photo => ({
    id: photo.id,
    group: photo.plant_species,
    content: photo.filename,
    type: 'box',
    start: photo.timestamp_ms,
    end: photo.timestamp_ms + 3600000, // Add 1 hour to make boxes visible
    className: 'timeline-photo-item',
    style: '',
    photo: photo
  }));
});

// Group photos by species for the timeline
const timelineGroups = computed(() => {
  const speciesSet = new Set(photos.value.map(photo => photo.plant_species));
  return Array.from(speciesSet).map(species => ({
    id: species,
    content: species
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

// Photo URL helper
const getPhotoUrl = (photoId) => {
  return `${baseUrlApi}/api/photos/${photoId}`;
};

// Handle filter changes
const handleFilterChange = () => {
  fetchPhotos();
};

// Handle timeline item click to show photo
const handleTimelineItemClick = (item) => {
  // Find the photo in our array
  const photo = photos.value.find(p => p.id === item.id);
  
  if (photo) {
    zoomedPhoto.value = photo;
    showLightbox.value = true;
  }
};

// Close lightbox
const closeLightbox = () => {
  showLightbox.value = false;
  zoomedPhoto.value = null;
};

// Watch for time range changes
watch(timeRange, () => {
  fetchPhotos();
});

// Fetch data on component mount
onMounted(() => {
  fetchPhotos();
});
</script>

<template>
  <div class="photo-gallery-container">
    <h2>Plant Photo Gallery</h2>

    <!-- Controls section -->
    <div class="controls">
      <div class="control-group">
        <label for="time-range">Time Range:</label>
        <select id="time-range" v-model="timeRange">
          <option v-for="option in timeRangeOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </div>

      <div class="control-group">
        <label for="species-filter">Plant Species:</label>
        <select id="species-filter" v-model="selectedSpecies" @change="handleFilterChange">
          <option value="">All Species</option>
          <option v-for="species in filterOptions.species" :key="species" :value="species">
            {{ species }}
          </option>
        </select>
      </div>

      <div class="control-group">
        <label for="location-filter">Location:</label>
        <select id="location-filter" v-model="selectedLocation" @change="handleFilterChange">
          <option value="">All Locations</option>
          <option v-for="location in filterOptions.locations" :key="location" :value="location">
            {{ location }}
          </option>
        </select>
      </div>
    </div>

    <!-- Loading, error, and no data states -->
    <div v-if="loading" class="loading-overlay">
      <div class="spinner"></div>
      <p>Loading photos...</p>
    </div>

    <div v-if="error" class="error-message">
      <p>{{ error }}</p>
      <button @click="fetchPhotos">Try Again</button>
    </div>

    <div v-if="!loading && !error && photos.length === 0" class="no-data">
      <p>No photos available for the selected filters.</p>
    </div>

    <!-- Timeline visualization -->
    <div v-if="!loading && !error && photos.length > 0" class="timeline-section">
      <h3>Photo Timeline</h3>
      
      <timeline 
        :groups="timelineGroups" 
        :items="timelineItems" 
        :viewportMin="visibleTimeRange.start"
        :viewportMax="visibleTimeRange.end"
        :clickable="true"
        @click-item="handleTimelineItemClick"
      >
        <template #item="props">
          <div class="timeline-item-content">
            <div class="timeline-thumbnail" 
                 :style="{ backgroundImage: `url(${getPhotoUrl(props.item.id)})` }"
                 @click="handleTimelineItemClick(props.item)">
            </div>
          </div>
        </template>
      </timeline>
    </div>

    <!-- Photo grid -->
    <div v-if="!loading && !error && photos.length > 0" class="photos-grid">
      <h3>Photo Gallery</h3>
      <div class="photo-grid">
        <div v-for="photo in photos" :key="photo.id" class="photo-item" @click="zoomedPhoto = photo; showLightbox = true">
          <div class="photo-thumbnail" :style="{ backgroundImage: `url(${getPhotoUrl(photo.id)})` }"></div>
          <div class="photo-info">
            <div class="photo-title">{{ photo.plant_species }}</div>
            <div class="photo-location">{{ photo.location }}</div>
            <div class="photo-date">{{ formatDate(photo.timestamp) }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Photo lightbox -->
    <div v-if="showLightbox && zoomedPhoto" class="lightbox" @click="closeLightbox">
      <div class="lightbox-content" @click.stop>
        <button class="close-button" @click="closeLightbox">&times;</button>
        <img :src="getPhotoUrl(zoomedPhoto.id)" :alt="zoomedPhoto.filename" class="lightbox-image">
        <div class="lightbox-info">
          <h3>{{ zoomedPhoto.plant_species }}</h3>
          <p>Location: {{ zoomedPhoto.location }}</p>
          <p>Date: {{ formatDate(zoomedPhoto.timestamp) }}</p>
          <p v-if="zoomedPhoto.metadata && zoomedPhoto.metadata.dimensions">
            Dimensions: {{ zoomedPhoto.metadata.dimensions }}
          </p>
          <p v-if="zoomedPhoto.metadata && zoomedPhoto.metadata.source">
            Source: {{ zoomedPhoto.metadata.source }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.photo-gallery-container {
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
    margin-bottom: 15px;
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
      min-width: 180px;

      &:focus {
        outline: none;
        border-color: #66afe9;
        box-shadow: 0 0 5px rgba(102, 175, 233, 0.5);
      }
    }
  }
}

.loading-overlay {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  padding: 40px;
  background: rgba(255, 255, 255, 0.8);

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
    to {
      transform: rotate(360deg);
    }
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
  height: 200px;
  background-color: #f9f9f9;
  border: 1px dashed #ccc;
  border-radius: 4px;

  p {
    color: #777;
    font-style: italic;
  }
}

.timeline-section {
  margin-bottom: 40px;
  background-color: white;
  padding: 15px;
  border-radius: 6px;
  box-shadow: 0 1px 5px rgba(0, 0, 0, 0.1);
}

.timeline-item-content {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.timeline-thumbnail {
  width: 60px;
  height: 60px;
  background-size: cover;
  background-position: center;
  border-radius: 4px;
  cursor: pointer;
  box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
  transition: transform 0.2s;

  &:hover {
    transform: scale(1.05);
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
  }
}

.photos-grid {
  background-color: white;
  padding: 15px;
  border-radius: 6px;
  box-shadow: 0 1px 5px rgba(0, 0, 0, 0.1);
}

.photo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 20px;
}

.photo-item {
  background-color: white;
  border-radius: 6px;
  overflow: hidden;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
  transition: transform 0.2s;
  cursor: pointer;

  &:hover {
    transform: translateY(-5px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  }
}

.photo-thumbnail {
  height: 200px;
  background-size: cover;
  background-position: center;
}

.photo-info {
  padding: 12px;
}

.photo-title {
  font-weight: 600;
  margin-bottom: 5px;
  color: #333;
}

.photo-location {
  font-size: 14px;
  color: #666;
  margin-bottom: 5px;
}

.photo-date {
  font-size: 12px;
  color: #888;
}

.lightbox {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.85);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
}

.lightbox-content {
  position: relative;
  max-width: 90%;
  max-height: 90%;
  display: flex;
  flex-direction: column;
  background-color: white;
  border-radius: 8px;
  overflow: hidden;
}

.close-button {
  position: absolute;
  top: 10px;
  right: 10px;
  background: rgba(0, 0, 0, 0.5);
  color: white;
  border: none;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  font-size: 20px;
  cursor: pointer;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;

  &:hover {
    background: rgba(0, 0, 0, 0.7);
  }
}

.lightbox-image {
  max-width: 100%;
  max-height: 70vh;
  object-fit: contain;
}

.lightbox-info {
  padding: 15px;
  background-color: white;

  h3 {
    margin-top: 0;
    margin-bottom: 10px;
    color: #333;
  }

  p {
    margin: 5px 0;
    color: #666;
  }
}
</style>
