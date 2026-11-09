# operator-brain transcript tools

Rebuilds the operator prompt corpus that seeds the Brain (see `documents/universal-system-design.md` §6).
Outputs contain private prompts — write them outside the repo. Never commit the corpus.

```
OUT=~/.autoplan/brain; mkdir -p $OUT
python3 -I tools/operator-brain/extract.py  $OUT/corpus.jsonl     # ~80 s, all local agent stores
python3 -I tools/operator-brain/clean.py    $OUT/corpus.jsonl $OUT/clean.jsonl   # dedupe + secret redaction
python3 -I tools/operator-brain/analyze.py  $OUT/clean.jsonl $OUT/examples.json  # volume, repos, categories
python3 -I tools/operator-brain/signals.py  $OUT/clean.jsonl                     # corrections, relays, approvals
```

Sources read (read-only; operator-typed turns only, subagent/exec threads skipped):

| Service | Store | User-turn selector |
|---|---|---|
| Antigravity IDE / CLI | `~/.gemini/antigravity{,-cli}/conversations/*.db` | `steps.step_type = 14` (protobuf payload, longest text run) |
| Codex | `~/.codex/sessions/**/rollout-*.jsonl.zst`, `archived_sessions/` | `response_item` `message` role `user`; skip `thread_source=subagent`, `codex_exec` |
| Cursor | `~/.cursor/chats/*/*/store.db` | `blobs` JSON role `user`, `<user_query>` body |
| MiniMax (CLI) | `~/.minimax/v2/sessions/**/messages.jsonl` | role `user`, root sessions only. Desktop-app chats are not stored locally. |
| MiMo (desktop + mimocode) | `~/.local/share/mimocode/mimocode.db` | `message.role=user`, `agent_id=main`, no parent session, non-synthetic text parts |
| Muse | `~/.local/share/muse/sessions/**/session.jsonl` | `runtime.user_intent.accepted`, `semantic_kind=chat`, root session dirs |
| Claude Code | `~/.claude/projects/*/*.jsonl` | `type=user`, not sidechain/meta |

Known limits: Antigravity rows have no timestamps and may keep 1–2 stray protobuf bytes at the start; keyword
categories are regex heuristics (counts are lower bounds, not classifier output).
