<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// A small line-icon set (24x24, stroke = currentColor), drawn for this app.
import type { IconName } from '../../lib/icons';
defineProps<{ name: IconName }>();
</script>

<template>
	<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
		<template v-if="name === 'home'"><rect x="3" y="3" width="7.5" height="9" /><rect x="13.5" y="3" width="7.5" height="5" /><rect x="13.5" y="11" width="7.5" height="10" /><rect x="3" y="15" width="7.5" height="6" /></template>
		<template v-else-if="name === 'table'"><rect x="3" y="4" width="18" height="16" rx="1" /><path d="M3 9h18M3 14.5h18M9 4v16M15 4v16" /></template>
		<template v-else-if="name === 'compare'"><rect x="3" y="4" width="7" height="16" rx="1" /><rect x="14" y="4" width="7" height="16" rx="1" /><path d="M10 9h4m-1.5-1.5L14 9l-1.5 1.5M14 15h-4m1.5-1.5L10 15l1.5 1.5" /></template>
		<template v-else-if="name === 'symbol'"><circle cx="12" cy="9" r="5.5" /><path d="M7.5 9h9M12 14.5V21M5 21h14" /></template>
		<template v-else-if="name === 'list'"><path d="M9 6h11M9 12h11M9 18h11" /><circle cx="4.5" cy="6" r="1" /><circle cx="4.5" cy="12" r="1" /><circle cx="4.5" cy="18" r="1" /></template>
		<template v-else-if="name === 'database'"><ellipse cx="12" cy="5.5" rx="7.5" ry="2.5" /><path d="M4.5 5.5v13c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5v-13M4.5 12c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5" /></template>
		<template v-else-if="name === 'cpu'"><rect x="6" y="6" width="12" height="12" rx="1" /><rect x="9.5" y="9.5" width="5" height="5" /><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" /></template>
		<template v-else-if="name === 'logo'"><rect x="2.5" y="3" width="8" height="6" rx="1" /><rect x="13.5" y="15" width="8" height="6" rx="1" /><circle cx="18" cy="6" r="3" /><path d="M10.5 6h4.5M6.5 9v9h7" /><path d="M11.5 16l2 2-2 2" /></template>
		<template v-else-if="name === 'run' || name === 'play'"><circle cx="12" cy="12" r="9" /><path d="M10 8.5v7l5.5-3.5z" /></template>
		<template v-else-if="name === 'file' || name === 'pages'"><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4M9 13h6M9 17h4" /></template>
		<template v-else-if="name === 'upload'"><path d="M12 15V4m-4 4l4-4 4 4M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" /></template>
		<template v-else-if="name === 'recipe'"><path d="M4 6h10M4 12h6M4 18h10" /><circle cx="17" cy="6" r="2" /><circle cx="13" cy="12" r="2" /><circle cx="17" cy="18" r="2" /><path d="M19 6h1M15 12h5M19 18h1" /></template>
		<template v-else-if="name === 'enum'"><rect x="3" y="4" width="18" height="16" rx="1" /><path d="M7 9h2M11 9h6M7 13h2M11 13h6M7 17h2M11 17h6" /></template>
		<template v-else-if="name === 'plus'"><path d="M12 5v14M5 12h14" /></template>
		<template v-else-if="name === 'tag'"><path d="M3 12V4h8l10 10-8 8z" /><circle cx="7.5" cy="8" r="1.5" /></template>
		<template v-else-if="name === 'layers'"><path d="M12 3l9 5-9 5-9-5z" /><path d="M3 13l9 5 9-5" /></template>
	</svg>
</template>
