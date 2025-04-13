<script>
import { Timeline } from 'vue-timeline-chart';
import 'vue-timeline-chart/style.css';
import LineChart from './LineChart.vue';

const itemsComposite = [
  { id: 1, group: 1, type: 'range', cssVariables: { '--item-background': 'var(--color-2)' }, start: 1000000, end: 4500000 },
  { id: 3, group: 1, type: 'range', start: 6000000, end: 8000000 },
];

const linechartData = [{ group: 'linechart', value: 1, type: 'point', start: 1000000 },
{ group: 'linechart', value: 1, type: 'point', start: 1500000 },
{ group: 'linechart', value: 0.7, type: 'point', start: 2000000 },
{ group: 'linechart', value: 0, type: 'point', start: 2500000 },
{ group: 'linechart', value: 1, type: 'point', start: 3000000 },
{ group: 'linechart', value: 0, type: 'point', start: 3500000 },
{ group: 'linechart', value: 0, type: 'point', start: 4000000 },
{ group: 'linechart', value: 0, type: 'point', start: 4500000 },
{ group: 'linechart', value: 1, type: 'point', start: 5000000 },
{ group: 'linechart', value: 0.5, type: 'point', start: 5500000 },
{ group: 'linechart', value: 1, type: 'point', start: 6000000 },
{ group: 'linechart', value: 1, type: 'point', start: 6500000 },
{ group: 'linechart', value: 0.6, type: 'point', start: 7000000 },
];
const groups = [
  { id: 'group1', label: 'Group 1' },
  { id: 'group2', label: 'Group 2' },
];

const items = [
  { group: 'group1', type: 'point', start: 1705878000000, cssVariables: { '--item-background': 'var(--color-2)' } },
  { group: 'group1', type: 'range', start: 1707135072000, end: 1708431072000, cssVariables: { '--item-background': 'var(--color-4)' } },
  { group: 'group2', type: 'range', start: 1706790600000, end: 1706877000000 },
];

export default {
  data() {
    return {
      items: items,
      groups: groups,
      linechartData: linechartData,
      itemsComposite: itemsComposite
    };
  },
  components: {
    timeline: Timeline, 
    LineChart: LineChart
  },
  methods: {

  },
  created() {
  },
};
</script>

<template>

  <timeline :groups="groups" :items="items" :viewportMin="1703112200000" :viewportMax="1714566600000" />

  <timeline :items="itemsComposite" :groups="[{ id: 1 }, { id: 'linechart' }]" :viewportMin="0" :viewportMax="8000000">

    <template #items-linechart="{ viewportStart, viewportEnd, group }">
      <LineChart :viewportStart="viewportStart" :viewportEnd="viewportEnd" :data="linechartData" />
    </template>
  </timeline>
</template>