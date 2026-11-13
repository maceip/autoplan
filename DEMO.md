# AutoPlan + WebClaw Multi-Agent Demo

## Remotes

- **AutoPlan**: `https://github.com/maceip/autoplan.git` (`origin`)
- **WebClaw Frontend**: `https://github.com/maceip/webclaw.git` (also bundled in `webclaw/`)

## Registered Lead Agent Services

1. **Antigravity (`antigravity`)** — headless dispatch via `agy -p=... --output-format=json` + local SQLite session discovery (`~/.gemini/antigravity*/conversations/*.db`).
2. **Xiaomi MiMo (`xiaomi-mimo`)** — headless dispatch via `mimo run --format json -m <provider/model>` + local SQLite session discovery (`~/.local/share/mimocode/mimocode.db`).
3. **MiniMax (`minimax`)** — local session & config discovery (`~/.minimax/v2/sessions/**/messages.jsonl`, `~/.minimax/config.yaml`). Reports `observe_only` when `MINIMAX_API_KEY` is unset and switches to live tool-loop dispatch when `MINIMAX_API_KEY` (or `provider.minimax.options.apiKey`) is configured.

## Quickstart

### 1. Start the AutoPlan Backend + Chief of Staff

```bash
# From the repo root (--root-path must point at the repo root: it bounds
# workspace dirs, the queue DB at .planai-queue/, and which repos may be merged)
cd backend
.venv/bin/python -m planaieditor.app --root-path .. --host 127.0.0.1 --port 5051
```

### 2. Start the WebClaw Workbench Frontend

```bash
cd webclaw
COREPACK_ENABLE_DOWNLOAD_PROMPT=0 AUTOPLAN_BACKEND_URL=http://127.0.0.1:5051 pnpm -C apps/webclaw dev --host 127.0.0.1 --port 3050
```

Open `http://127.0.0.1:3050`:
- Select **Xiaomi MiMo** or **Antigravity** in the header service selector and click **Run Simple Task** (or send any prompt in chat).
- Watch the live subprocess create an isolated git branch in `.planai-queue/demo-workspaces/<run_id>`, commit `task_result.txt`, pass the Chief-of-Staff verification test (`Test exit 0 (passed)`), and reach `needs_review` in the right-hand **Queue** inspector.
- Click **Approve** to merge onto `main` (`landed`).
- Or click **Request changes** with a note: the Chief re-dispatches the item to its source agent in the same workspace and branch; the agent's new commit flows back through triage, tests, and review automatically.

## Automated Verification

```bash
# Unit & API tests
cd backend
.venv/bin/pytest tests/test_queue.py tests/test_agents_and_webclaw_api.py -q

# End-to-end Playwright verification (requires backend on :5051 and WebClaw on :3050)
FRONTEND_URL=http://127.0.0.1:5051 BACKEND_TEST_PORT=5051 WEBCLAW_URL=http://127.0.0.1:3050 \
  .venv/bin/pytest tests/e2e/test_queue_ui.py tests/e2e/test_webclaw_e2e.py -v
```
