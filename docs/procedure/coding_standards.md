# Coding Standards

## Vue 3 Conventions

- Use **Composition API** with `<script setup>` syntax exclusively.
- Use **TypeScript** for all `.vue` and `.ts` files.
- Component files: **PascalCase** (e.g., `CctvCard.vue`).
- Data files: **camelCase** (e.g., `kecamatan.ts`, `cctv.ts`).

## Component Structure

```vue
<script setup lang="ts">
// Imports
// Props definition
// Emits definition
// Composables / State
// Computed / Methods
</script>

<template>
  <!-- Template markup -->
</template>
```

## Styling

- Use **Tailwind CSS utility classes** exclusively.
- Avoid custom CSS files. Use `@apply` only in rare cases via `<style scoped>`.
- Follow the dark monitoring theme: dark backgrounds, green (online), yellow (warning), red (offline), blue (accent).

## Naming

- Props: `camelCase`
- Emits: `camelCase` (e.g., `selectDistrict`)
- Composables: `use` prefix (e.g., `useMonitoring`)
- Interfaces: `PascalCase` without `I` prefix (e.g., `Camera`, `District`)

## Formatting

- Single file components (SFC).
- No semicolons.
- Single quotes for strings.
- Trailing commas in multiline objects/arrays.
