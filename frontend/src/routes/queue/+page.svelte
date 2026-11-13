<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { io, type Socket } from 'socket.io-client';
	import { backendUrl } from '$lib/utils/backendUrl';

	type QueueItem = {
		id: string;
		source_agent: string;
		kind: string;
		title: string;
		body: string;
		repo_path: string;
		branch: string;
		target_branch: string;
		test_command: string;
		demo_url: string;
		priority: number;
		status: string;
		recommendation: string;
		evidence: Record<string, string>;
		result: Record<string, unknown>;
		created_at: number;
		updated_at: number;
	};
	type QueueEvent = { type: string; message: string; created_at: number };
	type QueueDecision = { action: string; note: string; actor: string; created_at: number };
	type AgentService = {
		service: string;
		display_name: string;
		mode: 'dispatch' | 'observe_only';
		dispatch_ready: boolean;
		default_model: string;
		observed_sessions_count: number;
		auth_status: string;
	};

	const STATUS_FILTERS = [
		'',
		'needs_review',
		'queued',
		'triaged',
		'in_progress',
		'approved',
		'landing',
		'landed',
		'done',
		'changes_requested',
		'snoozed',
		'rejected',
		'failed'
	];
	const DECISION_ACTIONS: Record<string, string[]> = {
		approve: ['needs_review'],
		request_changes: ['needs_review'],
		reject: ['needs_review', 'queued', 'triaged', 'in_progress'],
		snooze: ['needs_review', 'queued', 'triaged']
	};

	let items = $state<QueueItem[]>([]);
	let selectedId = $state<string | null>(null);
	let detail = $state<{ item: QueueItem; events: QueueEvent[]; decisions: QueueDecision[] } | null>(null);
	let statusFilter = $state('');
	let counts = $state<Record<string, number>>({});
	let chiefStatus = $state('');
	let agentServices = $state<AgentService[]>([]);
	let selectedDemoService = $state('');
	let spinningDemo = $state(false);
	let errorMessage = $state('');
	let changesNote = $state('');
	let showChangesForm = $state(false);
	let evidenceExpanded = $state(true);
	let socket: Socket | null = null;
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	let form = $state({
		source_agent: 'human',
		kind: 'task',
		title: '',
		body: '',
		repo_path: '',
		branch: '',
		target_branch: 'main',
		test_command: '',
		demo_url: ''
	});

	const selectedIndex = $derived(items.findIndex((item) => item.id === selectedId));
	const selectedItem = $derived(
		(detail?.item.id === selectedId ? detail.item : null) ??
			items.find((item) => item.id === selectedId) ??
			null
	);

	async function api(path: string, options?: RequestInit): Promise<Record<string, unknown>> {
		const response = await fetch(`${backendUrl}${path}`, {
			headers: { 'Content-Type': 'application/json' },
			...options
		});
		const payload = await response.json();
		if (!response.ok || payload.success === false) {
			throw new Error(payload.error ?? `Request failed with HTTP ${response.status}`);
		}
		return payload;
	}

	async function refreshList() {
		try {
			const query = statusFilter ? `?status=${statusFilter}` : '';
			const payload = await api(`/api/queue/items${query}`);
			items = payload.items as QueueItem[];
			if (selectedId === null && items.length > 0) {
				await selectItem(items[0].id);
			} else if (selectedId !== null && !items.some((item) => item.id === selectedId)) {
				detail = null;
				selectedId = items.length > 0 ? items[0].id : null;
				if (selectedId) await selectItem(selectedId);
			}
			const stats = await api('/api/queue/stats');
			counts = stats.counts as Record<string, number>;
			chiefStatus = (stats.chief as Record<string, unknown>).llm_status as string;
			const agentsPayload = await api('/api/agents');
			agentServices = (agentsPayload.services as AgentService[]) ?? [];
			if (!selectedDemoService && agentServices.length > 0) {
				selectedDemoService =
					(agentsPayload.default_service as string) ?? agentServices[0].service;
			}
			errorMessage = '';
		} catch (error) {
			errorMessage = error instanceof Error ? error.message : String(error);
		}
	}

	async function runDemoTask() {
		if (!selectedDemoService) return;
		spinningDemo = true;
		try {
			await api('/api/agents/demo-task', {
				method: 'POST',
				body: JSON.stringify({ service: selectedDemoService })
			});
			await refreshList();
		} catch (error) {
			errorMessage = error instanceof Error ? error.message : String(error);
		} finally {
			spinningDemo = false;
		}
	}

	async function selectItem(itemId: string) {
		if (selectedId !== itemId) {
			showChangesForm = false;
			changesNote = '';
			detail = null;
		}
		selectedId = itemId;
		try {
			const fetched = (await api(`/api/queue/items/${itemId}`)) as unknown as {
				item: QueueItem;
				events: QueueEvent[];
				decisions: QueueDecision[];
			};
			if (selectedId === itemId) {
				detail = fetched;
			}
		} catch (error) {
			errorMessage = error instanceof Error ? error.message : String(error);
		}
	}

	async function decide(action: string, note = '') {
		if (!selectedItem) return;
		const targetId = selectedItem.id;
		try {
			await api(`/api/queue/items/${targetId}/decision`, {
				method: 'POST',
				body: JSON.stringify({ action, note, actor: 'human-queue-ui' })
			});
			showChangesForm = false;
			changesNote = '';
			await refreshList();
			await selectItem(targetId);
		} catch (error) {
			errorMessage = error instanceof Error ? error.message : String(error);
		}
	}

	async function wake() {
		if (!selectedItem) return;
		const targetId = selectedItem.id;
		try {
			await api(`/api/queue/items/${targetId}/wake`, { method: 'POST', body: '{}' });
			await refreshList();
			await selectItem(targetId);
		} catch (error) {
			errorMessage = error instanceof Error ? error.message : String(error);
		}
	}

	async function submitForm(event: SubmitEvent) {
		event.preventDefault();
		try {
			const payload = await api('/api/queue/items', {
				method: 'POST',
				body: JSON.stringify(form)
			});
			form.title = '';
			form.body = '';
			await refreshList();
			await selectItem((payload.item as QueueItem).id);
		} catch (error) {
			errorMessage = error instanceof Error ? error.message : String(error);
		}
	}

	function canDecide(action: string): boolean {
		return selectedItem !== null && (DECISION_ACTIONS[action] ?? []).includes(selectedItem.status);
	}

	function evidenceUrl(filename: string): string {
		return `${backendUrl}/api/queue/evidence/${selectedItem?.id}/${filename}`;
	}

	function testResult(item: QueueItem | null): Record<string, unknown> | null {
		const test = item?.result?.test;
		return test !== null && typeof test === 'object' ? (test as Record<string, unknown>) : null;
	}

	function onKeydown(event: KeyboardEvent) {
		const target = event.target as HTMLElement | null;
		if (target !== null && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
		if (event.key === 'j' && selectedIndex < items.length - 1) void selectItem(items[selectedIndex + 1].id);
		else if (event.key === 'k' && selectedIndex > 0) void selectItem(items[selectedIndex - 1].id);
		else if (event.key === 'a' && canDecide('approve')) void decide('approve');
		else if (event.key === 'r' && canDecide('reject')) void decide('reject');
		else if (event.key === 's' && canDecide('snooze')) void decide('snooze');
		else if (event.key === 'x' && canDecide('request_changes')) showChangesForm = true;
		else if (event.key === 'e') evidenceExpanded = !evidenceExpanded;
	}

	// Voice control: Web Speech API transcript -> same decision actions, always behind an on-screen confirmation.
	let voiceSupported = $state(false);
	let voiceListening = $state(false);
	let pendingVoice = $state<{ transcript: string; action: string; note: string } | null>(null);

	function startVoice() {
		const recognitionConstructor =
			(window as unknown as Record<string, unknown>).SpeechRecognition ??
			(window as unknown as Record<string, unknown>).webkitSpeechRecognition;
		if (typeof recognitionConstructor !== 'function') return;
		const recognition = new (recognitionConstructor as new () => Record<string, unknown>)();
		recognition.lang = 'en-US';
		recognition.onresult = (speechEvent: { results: { 0: { 0: { transcript: string } } } }) => {
			const transcript = speechEvent.results[0][0].transcript.trim().toLowerCase();
			voiceListening = false;
			if (transcript.startsWith('approve')) pendingVoice = { transcript, action: 'approve', note: '' };
			else if (transcript.startsWith('reject')) pendingVoice = { transcript, action: 'reject', note: '' };
			else if (transcript.startsWith('snooze')) pendingVoice = { transcript, action: 'snooze', note: '' };
			else if (transcript.startsWith('request changes'))
				pendingVoice = { transcript, action: 'request_changes', note: transcript.replace('request changes', '').trim() };
			else errorMessage = `Voice command not recognized: "${transcript}". Say approve, reject, snooze, or request changes.`;
		};
		recognition.onerror = () => {
			voiceListening = false;
			errorMessage = 'Voice recognition error. Keyboard and buttons remain available.';
		};
		recognition.onend = () => {
			voiceListening = false;
		};
		voiceListening = true;
		(recognition as unknown as { start: () => void }).start();
	}

	onMount(() => {
		voiceSupported =
			typeof (window as unknown as Record<string, unknown>).SpeechRecognition === 'function' ||
			typeof (window as unknown as Record<string, unknown>).webkitSpeechRecognition === 'function';
		void refreshList();
		socket = io(backendUrl || window.location.origin);
		socket.on('queue_updated', () => {
			void refreshList().then(() => {
				if (selectedId && !showChangesForm) void selectItem(selectedId);
			});
		});
		pollTimer = setInterval(() => {
			void refreshList().then(() => {
				if (selectedId && !showChangesForm) void selectItem(selectedId);
			});
		}, 4000);
		window.addEventListener('keydown', onKeydown);
	});

	onDestroy(() => {
		socket?.disconnect();
		if (pollTimer) clearInterval(pollTimer);
		window.removeEventListener('keydown', onKeydown);
	});
</script>

<div class="min-h-screen bg-neutral-950 font-mono text-neutral-100">
	<header class="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-neutral-800 px-5 py-3">
		<h1 class="text-lg font-bold tracking-tight">Chief of Staff Queue</h1>
		<span data-testid="chief-llm-status" class="text-xs text-neutral-400">Chief LLM: {chiefStatus || 'loading…'}</span>
		<span class="text-xs text-neutral-400">
			{#each Object.entries(counts).filter(([, n]) => n > 0) as [status, n]}
				<span class="mr-3">{status}: <strong class="text-neutral-100">{n}</strong></span>
			{/each}
		</span>
		<span class="ml-auto flex items-center gap-3 text-xs">
			{#if agentServices.length > 0}
				<select
					aria-label="Demo task agent"
					data-testid="queue-agent-select"
					bind:value={selectedDemoService}
					class="border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs"
				>
					{#each agentServices as svc}
						<option value={svc.service} disabled={!svc.dispatch_ready}>
							{svc.display_name} ({svc.mode === 'dispatch' ? svc.default_model : 'observe_only'}) · {svc.observed_sessions_count}s
						</option>
					{/each}
				</select>
				<button
					type="button"
					data-testid="queue-demo-task-button"
					disabled={spinningDemo || !agentServices.find((s) => s.service === selectedDemoService)?.dispatch_ready}
					onclick={() => void runDemoTask()}
					class="border border-neutral-100 bg-neutral-100 px-3 py-1 font-bold text-neutral-950 disabled:opacity-40"
				>
					{spinningDemo ? 'Spinning up…' : 'Run Simple Task'}
				</button>
			{/if}
			<button
				type="button"
				data-testid="voice-button"
				disabled={!voiceSupported || !selectedItem}
				onclick={startVoice}
				class="border border-neutral-600 px-3 py-1.5 disabled:cursor-not-allowed disabled:opacity-40"
			>
				{voiceListening ? 'Listening…' : voiceSupported ? 'Voice command' : 'Voice unsupported in this browser'}
			</button>
			<a class="underline" href="/">Workflow editor</a>
		</span>
	</header>

	{#if errorMessage}
		<div data-testid="queue-error" role="alert" class="border-b border-red-900 bg-red-950 px-5 py-2 text-sm text-red-200">
			{errorMessage}
		</div>
	{/if}

	{#if pendingVoice && selectedItem}
		<div data-testid="voice-confirm" class="flex flex-wrap items-center gap-3 border-b border-amber-800 bg-amber-950 px-5 py-2 text-sm">
			<span>Heard: "{pendingVoice.transcript}" → <strong>{pendingVoice.action}</strong> on "{selectedItem.title}"?</span>
			<button
				type="button"
				data-testid="voice-confirm-yes"
				class="border border-amber-500 px-3 py-1"
				onclick={() => {
					const pending = pendingVoice;
					pendingVoice = null;
					if (pending) void decide(pending.action, pending.note);
				}}>Confirm</button
			>
			<button type="button" class="border border-neutral-600 px-3 py-1" onclick={() => (pendingVoice = null)}>Cancel</button>
		</div>
	{/if}

	<div class="grid grid-cols-1 gap-0 lg:grid-cols-[420px_1fr]">
		<section class="border-r border-neutral-800">
			<div class="flex flex-wrap gap-1 border-b border-neutral-800 px-3 py-2">
				{#each STATUS_FILTERS as status}
					<button
						type="button"
						data-testid={`filter-${status || 'all'}`}
						class="border px-2 py-1 text-xs {statusFilter === status
							? 'border-neutral-100 bg-neutral-100 text-neutral-950'
							: 'border-neutral-700 text-neutral-300'}"
						onclick={() => {
							statusFilter = status;
							void refreshList();
						}}>{status || 'all'}</button
					>
				{/each}
			</div>
			<ul data-testid="queue-list" class="max-h-[60vh] overflow-y-auto">
				{#each items as item}
					<li>
						<button
							type="button"
							data-testid={`queue-item-${item.id}`}
							class="block w-full border-b border-neutral-900 px-3 py-2 text-left {item.id === selectedId
								? 'bg-neutral-800'
								: 'hover:bg-neutral-900'}"
							onclick={() => void selectItem(item.id)}
						>
							<span class="flex items-baseline justify-between gap-2">
								<strong class="text-sm">{item.title}</strong>
								<span class="text-xs font-bold">P{item.priority}</span>
							</span>
							<span class="mt-0.5 block text-xs text-neutral-400">
								{item.kind} · {item.status} · from {item.source_agent}
							</span>
						</button>
					</li>
				{:else}
					<li class="px-3 py-6 text-sm text-neutral-500">Queue is empty for this filter.</li>
				{/each}
			</ul>

			<form onsubmit={submitForm} class="space-y-2 border-t border-neutral-800 px-3 py-3 text-xs">
				<h2 class="text-sm font-bold">Submit work</h2>
				<label class="block">Source agent
					<input data-testid="submit-source" bind:value={form.source_agent} class="mt-1 w-full border border-neutral-700 bg-neutral-900 px-2 py-1.5" />
				</label>
				<label class="block">Kind
					<select data-testid="submit-kind" bind:value={form.kind} class="mt-1 w-full border border-neutral-700 bg-neutral-900 px-2 py-1.5">
						<option value="task">task</option>
						<option value="code_change">code_change</option>
						<option value="decision">decision</option>
						<option value="comms">comms</option>
						<option value="idea">idea</option>
					</select>
				</label>
				<label class="block">Title
					<input data-testid="submit-title" bind:value={form.title} required class="mt-1 w-full border border-neutral-700 bg-neutral-900 px-2 py-1.5" />
				</label>
				<label class="block">Body
					<textarea bind:value={form.body} rows="3" class="mt-1 w-full border border-neutral-700 bg-neutral-900 px-2 py-1.5"></textarea>
				</label>
				<label class="block">Repo path (code_change)
					<input bind:value={form.repo_path} class="mt-1 w-full border border-neutral-700 bg-neutral-900 px-2 py-1.5" />
				</label>
				<div class="grid grid-cols-2 gap-2">
					<label class="block">Branch
						<input bind:value={form.branch} class="mt-1 w-full border border-neutral-700 bg-neutral-900 px-2 py-1.5" />
					</label>
					<label class="block">Target branch
						<input bind:value={form.target_branch} class="mt-1 w-full border border-neutral-700 bg-neutral-900 px-2 py-1.5" />
					</label>
				</div>
				<label class="block">Test command
					<input bind:value={form.test_command} placeholder="pytest -q" class="mt-1 w-full border border-neutral-700 bg-neutral-900 px-2 py-1.5" />
				</label>
				<label class="block">Demo URL (screenshot/video evidence)
					<input bind:value={form.demo_url} placeholder="http://localhost:…" class="mt-1 w-full border border-neutral-700 bg-neutral-900 px-2 py-1.5" />
				</label>
				<button type="submit" data-testid="submit-button" class="border border-neutral-100 bg-neutral-100 px-4 py-2 font-bold text-neutral-950">Submit to chief</button>
			</form>
		</section>

		<section data-testid="queue-detail" class="px-5 py-4">
			{#if selectedItem}
				<h2 class="text-xl font-bold">{selectedItem.title}</h2>
				<p class="mt-1 text-xs text-neutral-400">
					{selectedItem.kind} · status <strong class="text-neutral-100" data-testid="detail-status">{selectedItem.status}</strong>
					· priority {selectedItem.priority} · from {selectedItem.source_agent}
					{#if selectedItem.branch}· branch {selectedItem.branch} → {selectedItem.target_branch}{/if}
				</p>
				{#if selectedItem.recommendation}
					<p class="mt-3 border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm">
						<span class="font-bold">Chief recommendation:</span>
						{selectedItem.recommendation}
					</p>
				{/if}
				{#if selectedItem.body}
					<pre class="mt-3 overflow-x-auto border border-neutral-800 px-3 py-2 text-xs whitespace-pre-wrap">{selectedItem.body}</pre>
				{/if}

				{#if testResult(selectedItem) !== null}
					{@const test = testResult(selectedItem)}
					<h3 class="mt-4 text-sm font-bold">
						Test run: <span data-testid="test-exit-code">exit {String(test?.exit_code)}</span>
						({test?.passed === true ? 'passed' : 'failed'}) — {String(test?.command)}
					</h3>
					<pre class="mt-1 max-h-48 overflow-auto border border-neutral-800 px-3 py-2 text-xs whitespace-pre-wrap">{String(test?.stdout_tail ?? '')}{String(test?.stderr_tail ?? '')}</pre>
				{/if}

				{#if selectedItem.evidence.screenshot || selectedItem.evidence.video}
					<h3 class="mt-4 text-sm font-bold">Evidence <span class="font-normal text-neutral-500">(e toggles)</span></h3>
					{#if evidenceExpanded}
						<div class="mt-2 space-y-3">
							{#if selectedItem.evidence.screenshot}
								<img data-testid="evidence-screenshot" src={evidenceUrl(selectedItem.evidence.screenshot)} alt="Captured screenshot of the demo URL" class="max-w-full border border-neutral-800" />
							{/if}
							{#if selectedItem.evidence.video}
								<video data-testid="evidence-video" src={evidenceUrl(selectedItem.evidence.video)} controls class="max-w-full border border-neutral-800">
									<track kind="captions" />
								</video>
							{/if}
						</div>
					{/if}
				{/if}

				<div class="mt-5 flex flex-wrap gap-2 text-sm">
					<button type="button" data-testid="approve-button" disabled={!canDecide('approve')} onclick={() => void decide('approve')} class="border border-green-500 px-4 py-2 font-bold disabled:cursor-not-allowed disabled:opacity-30">Approve (a)</button>
					<button type="button" data-testid="request-changes-button" disabled={!canDecide('request_changes')} onclick={() => (showChangesForm = true)} class="border border-amber-500 px-4 py-2 font-bold disabled:cursor-not-allowed disabled:opacity-30">Request changes (x)</button>
					<button type="button" data-testid="reject-button" disabled={!canDecide('reject')} onclick={() => void decide('reject')} class="border border-red-500 px-4 py-2 font-bold disabled:cursor-not-allowed disabled:opacity-30">Reject (r)</button>
					<button type="button" data-testid="snooze-button" disabled={!canDecide('snooze')} onclick={() => void decide('snooze')} class="border border-neutral-500 px-4 py-2 font-bold disabled:cursor-not-allowed disabled:opacity-30">Snooze (s)</button>
					{#if selectedItem.status === 'snoozed' || selectedItem.status === 'failed'}
						<button type="button" data-testid="wake-button" onclick={() => void wake()} class="border border-neutral-100 px-4 py-2 font-bold">Wake / retry</button>
					{/if}
				</div>
				{#if showChangesForm}
					<div class="mt-3 flex gap-2">
						<input data-testid="changes-note" bind:value={changesNote} placeholder="What must change?" class="flex-1 border border-neutral-700 bg-neutral-900 px-2 py-2 text-sm" />
						<button type="button" data-testid="changes-submit" onclick={() => void decide('request_changes', changesNote)} class="border border-amber-500 px-4 py-2 text-sm font-bold">Send back</button>
					</div>
				{/if}
				<p class="mt-3 text-xs text-neutral-500">Keys: j/k move · a approve · x request changes · r reject · s snooze · e evidence</p>

				{#if detail}
					<h3 class="mt-6 text-sm font-bold">Chief actions</h3>
					<ul class="mt-1 space-y-1 text-xs text-neutral-300">
						{#each detail.events as queueEvent}
							<li>{new Date(queueEvent.created_at * 1000).toLocaleTimeString()} · <strong>{queueEvent.type}</strong> · {queueEvent.message}</li>
						{:else}
							<li class="text-neutral-500">No chief actions recorded yet.</li>
						{/each}
					</ul>
					<h3 class="mt-4 text-sm font-bold">Operator decisions</h3>
					<ul class="mt-1 space-y-1 text-xs text-neutral-300">
						{#each detail.decisions as decision}
							<li>{new Date(decision.created_at * 1000).toLocaleTimeString()} · <strong>{decision.action}</strong> by {decision.actor}{decision.note ? ` · ${decision.note}` : ''}</li>
						{:else}
							<li class="text-neutral-500">No decisions recorded yet.</li>
						{/each}
					</ul>
				{/if}
			{:else}
				<p class="text-sm text-neutral-500">Select a queue item, or submit work for the chief.</p>
			{/if}
		</section>
	</div>
</div>

