<template>
    <div :id="chartId" class="chart-container">
        <div v-if="loading" class="loading">Loading data...</div>
        <div v-if="error" class="error">{{ error }}</div>
    </div>
</template>

<script lang="ts" setup>
import { onMounted, ref, watch, computed } from 'vue';
import * as d3 from "d3";

const props = defineProps({
    chartId: {
        type: String,
        default: 'temperature-chart'
    },
    title: {
        type: String,
        default: 'Temperature Data'
    },
    color: {
        type: String,
        default: '#ff7f0e'  // Orange color for temperature
    },
    data: {
        type: Array,
        default: () => []
    },
    timeRange: {
        type: Object,
        default: () => ({
            start: null,
            end: null
        })
    },
    yAxisLabel: {
        type: String,
        default: 'Temperature (°C)'
    },
    height: {
        type: Number,
        default: 400
    },
    timeFormat: {
        type: String,
        default: 'auto',  // 'auto', 'days', 'hours', 'minutes', 'seconds'
        validator: (value) => ['auto', 'days', 'hours', 'minutes', 'seconds'].includes(value)
    }
});

const loading = ref(false);
const error = ref(null);

// Calculate min/max values for auto-scaling
const yDomain = computed(() => {
    if (!props.data || props.data.length === 0) return [0, 30];  // Default range
    
    const values = props.data.map(d => d.value);
    const min = Math.floor(Math.min(...values) - 2);  // Pad min by 2 degrees
    const max = Math.ceil(Math.max(...values) + 2);   // Pad max by 2 degrees
    
    return [min, max];
});

// Calculate time domain for x-axis
const xDomain = computed(() => {
    if (props.timeRange.start && props.timeRange.end) {
        return [props.timeRange.start, props.timeRange.end];
    }
    
    if (!props.data || props.data.length === 0) {
        // Default to last 7 days if no data
        const end = new Date();
        const start = new Date();
        start.setDate(start.getDate() - 7);
        return [start.getTime(), end.getTime()];
    }
    
    // Use data range with small padding
    const timestamps = props.data.map(d => d.timestamp);
    const start = Math.min(...timestamps);
    const end = Math.max(...timestamps);
    const padding = (end - start) * 0.05;  // 5% padding on each side
    
    return [start - padding, end + padding];
});

function renderChart() {
    if (!props.data || props.data.length === 0) return;
    
    // Clear previous chart
    const chartContainer = document.getElementById(props.chartId);
    if (!chartContainer) return;
    
    d3.select(`#${props.chartId}`).selectAll('*').remove();
    
    // Set up dimensions
    const margin = { top: 40, right: 30, bottom: 50, left: 60 };
    const width = chartContainer.clientWidth - margin.left - margin.right;
    const height = props.height - margin.top - margin.bottom;
    
    // Create SVG
    const svg = d3.select(`#${props.chartId}`)
        .append('svg')
        .attr('width', width + margin.left + margin.right)
        .attr('height', height + margin.top + margin.bottom)
        .append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`);
    
    // Set up scales
    const x = d3.scaleTime()
        .domain(xDomain.value)
        .range([0, width]);
    
    const y = d3.scaleLinear()
        .domain(yDomain.value)
        .range([height, 0]);
    
    // Create axes
    const getTimeFormat = () => {
        // If auto mode, determine format based on time range
        if (props.timeFormat === 'auto') {
            const range = xDomain.value[1] - xDomain.value[0]; // time range in milliseconds
            
            // Less than 10 minutes
            if (range < 10 * 60 * 1000) {
                return d3.timeFormat('%H:%M:%S'); // Hours:Minutes:Seconds
            } 
            // Less than 3 hours
            else if (range < 3 * 60 * 60 * 1000) {
                return d3.timeFormat('%H:%M:%S'); // Hours:Minutes:Seconds 
            } 
            // Less than 2 days
            else if (range < 2 * 24 * 60 * 60 * 1000) {
                return d3.timeFormat('%H:%M'); // Hours:Minutes
            } 
            // Less than 30 days
            else if (range < 30 * 24 * 60 * 60 * 1000) {
                return d3.timeFormat('%b %d, %H:%M'); // Month Day, Hours:Minutes
            } 
            // More than 30 days
            else {
                return d3.timeFormat('%b %d'); // Month Day
            }
        } 
        
        // Explicit formats
        switch (props.timeFormat) {
            case 'days':
                return d3.timeFormat('%b %d');
            case 'hours':
                return d3.timeFormat('%b %d, %H:%M');
            case 'minutes':
                return d3.timeFormat('%H:%M');
            case 'seconds':
                return d3.timeFormat('%H:%M:%S');
            default:
                return d3.timeFormat('%b %d, %H:%M');
        }
    };
    
    const getTickCount = () => {
        // Base tick count based on width
        const baseTicks = width > 500 ? 10 : 5;
        
        // Adjust based on timeFormat
        if (props.timeFormat === 'seconds') {
            return baseTicks * 1.5; // More ticks for seconds
        } else if (props.timeFormat === 'minutes') {
            return baseTicks * 1.2; // Slightly more for minutes
        } else if (props.timeFormat === 'days') {
            return baseTicks * 0.7; // Fewer for days to avoid crowding
        } else {
            return baseTicks;
        }
    };
    
    const timeFormat = getTimeFormat();
    
    const xAxis = d3.axisBottom(x)
        .tickFormat(timeFormat)
        .ticks(getTickCount());
    
    const yAxis = d3.axisLeft(y)
        .ticks(height > 300 ? 10 : 5);
    
    // Add axes to chart
    svg.append('g')
        .attr('class', 'x-axis')
        .attr('transform', `translate(0,${height})`)
        .call(xAxis)
        .selectAll('text')
        .style('text-anchor', 'end')
        .attr('dx', '-.8em')
        .attr('dy', '.15em')
        .attr('transform', 'rotate(-45)');
    
    svg.append('g')
        .attr('class', 'y-axis')
        .call(yAxis);
    
    // Add y-axis label
    svg.append('text')
        .attr('transform', 'rotate(-90)')
        .attr('y', 0 - margin.left)
        .attr('x', 0 - (height / 2))
        .attr('dy', '1em')
        .style('text-anchor', 'middle')
        .text(props.yAxisLabel);
    
    // Add title
    svg.append('text')
        .attr('x', width / 2)
        .attr('y', 0 - (margin.top / 2))
        .attr('text-anchor', 'middle')
        .style('font-size', '16px')
        .text(props.title);
    
    // Create line generator
    const line = d3.line()
        .x(d => x(d.timestamp))
        .y(d => y(d.value))
        .curve(d3.curveMonotoneX);  // Smooth curve
    
    // Add line path
    svg.append('path')
        .datum(props.data)
        .attr('class', 'line')
        .attr('d', line)
        .style('fill', 'none')
        .style('stroke', props.color)
        .style('stroke-width', '2px');
    
    // Add data points
    svg.selectAll('.dot')
        .data(props.data)
        .enter()
        .append('circle')
        .attr('class', 'dot')
        .attr('cx', d => x(d.timestamp))
        .attr('cy', d => y(d.value))
        .attr('r', 4)
        .style('fill', props.color)
        .style('opacity', 0.7)
        .on('mouseover', function(event, d) {
            // Create tooltip on hover
            d3.select(this).attr('r', 6).style('opacity', 1);
            
            const date = new Date(d.timestamp);
            
            // Format the date based on the current time format setting
            let dateDisplay;
            if (props.timeFormat === 'seconds') {
                dateDisplay = date.toLocaleTimeString();
            } else if (props.timeFormat === 'minutes') {
                dateDisplay = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            } else if (props.timeFormat === 'hours') {
                dateDisplay = date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
            } else if (props.timeFormat === 'days') {
                dateDisplay = date.toLocaleDateString([], { month: 'short', day: 'numeric' });
            } else {
                // For 'auto' format, provide a comprehensive date time format
                dateDisplay = date.toLocaleString();
            }
            
            svg.append('text')
                .attr('id', 'tooltip')
                .attr('x', x(d.timestamp) + 10)
                .attr('y', y(d.value) - 10)
                .style('font-size', '12px')
                .text(`${d.value.toFixed(1)}°C at ${dateDisplay}`);
        })
        .on('mouseout', function() {
            // Remove tooltip on mouseout
            d3.select(this).attr('r', 4).style('opacity', 0.7);
            d3.select('#tooltip').remove();
        });
}

// Watch for changes in data or dimensions to redraw chart
watch(() => [props.data],
// watch(() => [props.data, chartId.value, width.value, height.value, xDomain.value, yDomain.value], 
    () => renderChart(),
    { deep: true }
);

// Watch for container size changes
onMounted(() => {
    renderChart();
    
    // Add window resize handler
    window.addEventListener('resize', renderChart);
    
    // Clean up event listener
    return () => {
        window.removeEventListener('resize', renderChart);
    };
});
</script>

<style lang="scss" scoped>
.chart-container {
    width: 100%;
    height: 100%;
    position: relative;
}

.loading, .error {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    font-size: 14px;
}

.error {
    color: red;
}

:deep(.line) {
    fill: none;
    stroke-width: 2px;
}

:deep(.x-axis), :deep(.y-axis) {
    font-size: 12px;
}

:deep(.x-axis path), :deep(.y-axis path) {
    stroke: #aaa;
}

:deep(.x-axis line), :deep(.y-axis line) {
    stroke: #ddd;
}
</style>