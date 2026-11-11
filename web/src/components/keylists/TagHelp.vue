<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// What a template row's cells can use: the row's own tags, the linked records' fields (dot
// notation, <<LoadType.Name>>) and the modifiers after | (<<Tag|upper>>). Opens as a panel.
import { ref } from 'vue';
import type { TagModifier } from '../../lib/keyListTypes';

defineProps<{ tags: { tag: string; meaning: string }[]; paths: { tag: string; meaning: string }[]; modifiers: TagModifier[] }>();
const open = ref(false);
</script>

<template>
	<span class="tag-help-wrap">
		<button type="button" class="link tag-help" :aria-expanded="open" @click="open = !open">All tags ⓘ</button>
		<div v-if="open" class="tag-help-panel" role="dialog" aria-label="Tags">
			<div class="row tight"><strong>What a cell can use</strong><span class="spacer" /><button type="button" class="secondary small" @click="open = false">✕</button></div>
			<p class="hint small">
				<code>&lt;&lt;path|modifier|modifier:arg&gt;&gt;</code>. Names ignore case, spaces and _. A link the row doesn't have gives
				blank (<code>|default:TBA</code> fills it); a name that isn't there is left as typed and listed as matching nothing.
			</p>
			<div class="tag-help-cols">
				<section>
					<h4>The row's tags</h4>
					<dl><template v-for="t in tags" :key="t.tag"><dt><code>{{ t.tag }}</code></dt><dd>{{ t.meaning }}</dd></template></dl>
				</section>
				<section>
					<h4>Linked records (dot notation)</h4>
					<dl><template v-for="t in paths" :key="t.tag"><dt><code>{{ t.tag }}</code></dt><dd>{{ t.meaning }}</dd></template></dl>
				</section>
				<section>
					<h4>Modifiers, after |</h4>
					<dl><template v-for="m in modifiers" :key="m.name"><dt><code>{{ m.example }}</code></dt><dd>{{ m.meaning }}</dd></template></dl>
				</section>
			</div>
		</div>
	</span>
</template>
