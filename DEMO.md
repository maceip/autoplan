# AutoPlan + WebClaw Multi-Agent Demo

## Live Hosted Demo (`https://queue.secure.build`)

- **WebClaw Workbench**: `https://queue.secure.build/`
- **Chief of Staff Queue UI**: `https://queue.secure.build/queue`
- **DNS (`secure.build`)**: Knot DNS `queue.secure.build. 300 A 142.248.222.1` (DNSSEC signed)
- **Reverse Proxy (`secure.build`)**: `/etc/caddy/Caddyfile` (`queue.secure.build` with HTTP Basic Auth + unbuffered SSE `flush_interval -1`):
  - `/` (WebClaw SSR & SSE routes) → `127.0.0.1:5198` (`autoplan-webclaw.service` running `/opt/autoplan-webclaw`)
  - `/queue*`, `/_app/*`, `/api/queue/*`, `/api/agents*`, `/api/ownership`, `/socket.io/*` → `100.80.211.36:5051` over Tailscale
- **Local Agent Bridge (Mac `100.80.211.36:5051`)**: Managed by `launchctl` (`~/Library/LaunchAgents/build.secure.autoplan-backend.plist`, `KeepAlive=true`) so `https://queue.secure.build` reaches local `Antigravity`, `Xiaomi MiMo`, and `MiniMax` stores and CLIs over WireGuard/Tailscale.

## Remotes

- **AutoPlan**: `https://github.com/maceip/autoplan.git` (`origin`)
- **WebClaw Frontend**: `https://github.com/maceip/webclaw.git` (also bundled in `webclaw/`)

## Registered Lead Agent Services

1. **Antigravity (`antigravity`)** — headless dispatch via `agy -p=... --output-format=json` + local SQLite session discovery (`~/.gemini/antigravity*/conversations/*.db`).
2. **Xiaomi MiMo (`xiaomi-mimo`)** — headless dispatch via `mimo run --format json -m <provider/model>` + local SQLite session discovery (`~/.local/share/mimocode/mimocode.db`).
3. **MiniMax (`minimax`)** — local session & config discovery (`~/.minimax/v2/sessions/**/messages.jsonl`, `~/.minimax/config.yaml`). Reports `observe_only` when `MINIMAX_API_KEY` is unset and switches to live tool-loop dispatch when `MINIMAX_API_KEY` (or `provider.minimax.options.apiKey`) is configured.

## Automated Verification

```bash
# Unit & API tests
cd /Users/mac/autoplan/backend
.venv/bin/pytest tests/test_queue.py tests/test_agents_and_webclaw_api.py -q

# Live Playwright E2E against https://queue.secure.build
E2E_HTTP_USER=autoplan E2E_HTTP_PASS="<demo-password>" \
  FRONTEND_URL=https://queue.secure.build \
  BACKEND_TEST_URL=https://queue.secure.build \
  WEBCLAW_URL=https://queue.secure.build \
  .venv/bin/pytest tests/e2e/test_queue_ui.py tests/e2e/test_webclaw_e2e.py -v
```
