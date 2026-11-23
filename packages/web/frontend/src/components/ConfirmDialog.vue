<script setup>
// A modal confirmation. Open it with the exposed ask(), which resolves true or false.
import { ref } from 'vue'

defineProps({ title: { type: String, required: true }, confirmLabel: { type: String, default: 'Confirm' } })
const dialog = ref(null)
let settle = null

function ask() {
  dialog.value.showModal()
  return new Promise((resolve) => { settle = resolve })
}
function close(answer) {
  dialog.value.close()
  settle?.(answer)
  settle = null
}
defineExpose({ ask })
</script>

<template>
  <dialog ref="dialog" @cancel.prevent="close(false)">
    <form method="dialog" @submit.prevent="close(true)">
      <h2>{{ title }}</h2>
      <div class="body"><slot /></div>
      <div class="buttons">
        <button type="button" class="plain" @click="close(false)">Cancel</button>
        <button type="submit" class="primary">{{ confirmLabel }}</button>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
dialog {
  border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); color: var(--text);
  padding: 1.25rem; width: min(28rem, calc(100vw - 2rem));
}
dialog::backdrop { background: rgb(0 0 0 / 0.5); }
form { display: grid; gap: 1rem; }
.body { display: grid; gap: 0.75rem; }
.buttons { display: flex; justify-content: flex-end; gap: 0.5rem; }
</style>
