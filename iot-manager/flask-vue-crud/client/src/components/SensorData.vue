<script setup lang="ts">
import { ref } from 'vue';
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

const itemsDraggable = ref([
  { id: 1, group: 1, type: 'range', cssVariables: { '--item-background': 'var(--color-2)' }, start: 1000000, end: 4500000 },
  { id: 2, group: 2, type: 'range', cssVariables: { '--item-background': 'var(--color-4)' }, start: 4500000, end: 6000000 },
  { id: 3, group: 3, type: 'range', start: 6000000, end: 8000000 },
]);

let previousDragTimePos = 0;
let currentDragAction: 'resize-start' | 'resize-both' | 'resize-end' | undefined;
let currentDragItemId = null;

function handleItemDrag({ time, event, item }) {
  // console.log('handleItemDrag', { time, event, item });
  // console.log(this)
  if (event.type === 'pointerdown') {
    if (!event.target.dataset.action) {
      return;
    }

    currentDragAction = event.target.dataset.action as typeof currentDragAction;
    currentDragItemId = item.id;
    previousDragTimePos = time;
  }
  else if (event.type === 'pointermove') {
    if (!currentDragAction) {
      return;
    }
    // console.log(currentDragItemId)
    // console.log(currentDragAction)
    const foundItem = itemsDraggable.value.find(i => i.id === currentDragItemId)!;
    const delta = time - previousDragTimePos;

    if (currentDragAction === 'resize-start' || currentDragAction === 'resize-both') {
      foundItem.start += delta;
    }
    if (currentDragAction === 'resize-end' || currentDragAction === 'resize-both') {
      foundItem.end += delta;
    }

    previousDragTimePos = time;
  }
}

window.addEventListener('pointerup', () => {
  currentDragAction = undefined;
}, { capture: true });

</script>

<template>

  <timeline :groups="groups" :items="items" :viewportMin="1703112200000" :viewportMax="1714566600000" />

  <timeline :items="itemsComposite" :groups="[{ id: 1 }, { id: 'linechart' }]" :viewportMin="0" :viewportMax="8000000">

    <template #items-linechart="{ viewportStart, viewportEnd, group }">
      <LineChart :viewportStart="viewportStart" :viewportEnd="viewportEnd" :data="linechartData" />
    </template>
  </timeline>

  <timeline :items="itemsDraggable" :groups="[{ id: 1 }, { id: 2 }, { id: 3 }]" :viewportMin="0" :viewportMax="8000000"
    @pointermove="handleItemDrag" @pointerdown="handleItemDrag">
    <template #item>
      <div class="draggable" data-action="resize-both">
        <div class="draggable-handle" data-action="resize-start"></div>
        <div class="draggable-handle" data-action="resize-end"></div>
      </div>
    </template>
  </timeline>
</template>

<style lang="scss" scoped>
.draggable {
  position: absolute;
  inset: 0;
  display: flex;
  justify-content: space-between;
  cursor: move;

  .draggable-handle {
    position: relative;
    width: 1.2rem;
    height: 100%;
    cursor: ew-resize;
    opacity: .6;

    &::before {
      content: '';
      border-inline: 1px solid white;
      width: 4px;
      height: 40%;
      left: 50%;
      top: 50%;
      transform: translate(-50%, -50%);
      position: absolute;
    }

    &:hover {
      opacity: 1;
    }
  }
}
</style>