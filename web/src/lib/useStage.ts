import { onMounted, ref, watch } from 'vue';
import type { PipelineResult, Recipe, Stage } from './melTypes';
import { useMel } from '../stores/mel';

/**
 * The pipeline output an editor works on (the table *before* its own rules).
 * Re-fetched when the rules of earlier stages change, so editing this stage's
 * own rules doesn't reload the table under the user.
 */
export function useStage(stage: Stage, upstream: (r: Recipe) => unknown) {
	const mel = useMel();
	const result = ref<PipelineResult | null>(null);
	let timer: ReturnType<typeof setTimeout> | undefined;

	async function refresh() {
		result.value = (await mel.runStage(stage)) ?? null;
	}

	onMounted(refresh);
	watch(
		() => (mel.draft ? JSON.stringify(upstream(mel.draft)) : ''),
		() => {
			clearTimeout(timer);
			timer = setTimeout(refresh, 300);
		},
	);
	return { result, refresh };
}
