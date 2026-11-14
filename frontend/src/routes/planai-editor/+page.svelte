<script lang="ts">
	import { onMount } from 'svelte';
	import EditorPage from '../+page.svelte';
	import { nodes, edges, getCurrentNodes } from '$lib/stores/graphStore';
	import { graphName } from '$lib/stores/graphNameStore.svelte';
	import { backendUrl } from '$lib/utils/backendUrl';
	import type { Node, Edge } from '@xyflow/svelte';

	onMount(async () => {
		try {
			const params = new URLSearchParams(window.location.search);
			let wfId = params.get('workflow_id') || '';
			if (!wfId && getCurrentNodes().length === 0) {
				const listRes = await fetch(`${backendUrl}/api/planai/workflows?limit=1`);
				if (listRes.ok) {
					const listData = (await listRes.json()) as { workflows?: Array<{ id: string }> };
					wfId = listData.workflows?.[0]?.id ?? '';
				}
			}
			if (wfId) {
				const res = await fetch(`${backendUrl}/api/planai/workflows/${encodeURIComponent(wfId)}/svelteflow`);
				if (res.ok) {
					const payload = (await res.json()) as {
						graph_name?: string;
						nodes?: Node[];
						edges?: Edge[];
					};
					if (payload.graph_name) {
						graphName.set(payload.graph_name);
					}
					if (Array.isArray(payload.nodes) && payload.nodes.length > 0) {
						nodes.set(payload.nodes);
					}
					if (Array.isArray(payload.edges)) {
						edges.set(payload.edges);
					}
				}
			}
		} catch {
			// SvelteFlow editor remains usable even if no workflow has run yet
		}
	});
</script>

<EditorPage />
