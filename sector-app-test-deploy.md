# sector-app test/verify loop

A change-triggered verification loop. Editing a source file arms it; ending the
turn runs it. It keeps re-running until every stage a change touched is green,
and finishes by pushing the work to GitHub.

Deploying to Railway is **not** part of the loop yet — it stays a deliberate
manual step (last section) until the Railway side is fully provisioned.

## Trigger

Two hooks in `.claude/settings.json`, both calling
`.claude/hooks/sector_loop.py`:

| Hook | Fires | Does |
| --- | --- | --- |
| `PostToolUse` on `Write\|Edit` | after every file edit | `stamp` — classifies the path, records which stages it invalidated. Silent, ~10 ms. |
| `Stop` | when the turn ends | `gate` — runs the deterministic stages itself; blocks the turn with instructions for the stages that need an agent. |

Every edit arms the loop; the stages run once per turn rather than once per
edit, so a run of ten edits costs one verification pass, not ten.

## Stages

| # | Stage | Command | Who runs it |
| --- | --- | --- | --- |
| 1 | `pytest` | `backend/.venv/Scripts/python -m pytest -q -p no:cacheprovider` in `backend/` | the hook |
| 2 | `build` | `npm run build` in `frontend/` | the hook |
| 3 | `stack` | `docker compose up --build -d`, then `GET :8000/health` and `GET :3000` both 200 | Claude, on instruction from the hook |
| 4 | `ui` | browser click-through of the changed surface at `localhost:3000`, console checked for errors | Claude, on instruction from the hook |
| 5 | `push` | `git add -A`, `git commit`, `git push origin <branch>` | Claude, on instruction from the hook |

Stages 1–2 are pure shell and run inside the hook (that is why its timeout is
900 s). Stages 3–5 need judgment — which page to open, what "working" looks
like, what the commit message should say — so the hook hands them back as a
blocking instruction and Claude executes them, then clears them.

Stage 1 failing short-circuits the pass: no minutes are spent on a Next build
while the tests are red. **Stage 5 is held back until 1–4 are all green** — the
hook does not even mention the push while anything local is still pending, so
nothing leaves the machine on a half-finished verification.

## What a change invalidates

`classify()` in `sector_loop.py`:

| Path | Stages |
| --- | --- |
| `backend/**/*.py` | 1, 3, 5 |
| `backend/app/api/**`, `backend/app/contracts/**` | 1, 3, 4, 5 — the wire surface deserves a real click-through |
| `frontend/**` (`.ts .tsx .js .jsx .mjs .css .json`) | 2, 3, 4, 5 |
| `docker-compose.yml`, any `Dockerfile` | 3, 4, 5 |
| `backend/requirements.txt` | 1, 3, 5 |
| `frontend/package.json`, `package-lock.json` | 2, 3, 4, 5 |
| `docs/`, `.claude/`, `data/`, `*.md`, `node_modules`, `.next`, `.venv` | none |

Anything worth verifying is worth pushing, so every non-empty result picks up
stage 5.

## The loop

```
edit ──▶ stamp: pending = {1,2,3,4,5}
              │
   turn ends  ▼
         gate: run 1, run 2
              ├─ a stage fails ──▶ block with the failing output
              │                     → fix → turn ends → gate runs again from 1
              ├─ 3 or 4 pending ─▶ block with instructions (5 stays hidden)
              │                     → Claude rebuilds / clicks through
              │                     → `sector_loop.py done stack ui`
              ├─ only 5 pending ─▶ block with the push instruction
              │                     → confirm → commit + push
              │                     → `sector_loop.py done push`
              └─ nothing pending ─▶ silent pass, "all stages green"
```

State lives in `.claude/.loop-state.json` (gitignored): the pending stages, the
files that armed them, the last git probe, and an attempt counter. Stages are
removed as they pass, so the loop converges rather than repeating work.

**Attempt cap.** The gate blocks at most `MAX_ATTEMPTS` (5) times per change
set. Beyond that it clears the state and says so, instead of wedging the
session in a block-fix-block cycle. Editing a file that adds a *new* stage
resets the counter — new ground gets a fresh budget.

## Push to git

Remote: **https://github.com/sdatch/sector-app**

The push stage only becomes real once the checkout has a remote. Until then the
gate drops it and records why, so an unconfigured repo never blocks a turn.
One-time setup:

```bash
git init && git branch -M main
git remote add origin https://github.com/sdatch/sector-app
git add -A && git commit -m "Sector Insight v1"
git push -u origin main
```

By default Claude **asks before pushing** — a push leaves the machine, so it is
a decision, not a side effect of saving a file. Set `SECTOR_LOOP_PUSH=auto` to
have every green pass push without asking. `SECTOR_LOOP_GIT_REMOTE` points the
stage at a remote other than `origin`.

## Manual controls

```bash
python .claude/hooks/sector_loop.py status          # what is pending and why
python .claude/hooks/sector_loop.py done stack ui   # mark agent stages complete
python .claude/hooks/sector_loop.py done push       # mark the push complete
python .claude/hooks/sector_loop.py reset           # disarm the loop
python .claude/hooks/sector_loop.py gate < /dev/null  # run a pass by hand
SECTOR_LOOP=off claude                              # disable both hooks
```

`/hooks` shows the hooks and can disable them from the UI. A hook edit only
takes effect in a session that was started after `.claude/` had a settings
file — otherwise open `/hooks` once, or restart, to reload.

The script never raises into the session: any unexpected error is written to
stderr and exits 0, so a broken loop cannot block work.

## Requirements

- `backend/.venv` exists with test deps (`pytest`, `pytest-asyncio`,
  `hypothesis`) — see CLAUDE.md "Running". Missing venv is reported as a
  stage-1 failure, not a crash.
- `frontend/node_modules` installed (`npm install`). Missing is reported as a
  stage-2 failure.
- Docker Desktop running for stage 3.
- Chrome with the Claude extension connected for stage 4.
- `git` with credentials for github.com for stage 5.

## Deploy (manual, outside the loop)

Run only when all five stages are green and you actually intend to ship:

1. Confirm green: `python .claude/hooks/sector_loop.py status` → `pending: none`.
2. Push to the branch Railway tracks (stage 5 already does this once Railway is
   pointed at the GitHub repo). `backend/railway.json` runs
   `alembic upgrade head` before uvicorn, so the schema migrates on deploy.
3. If the frontend's `NEXT_PUBLIC_API_URL` changed, rebuild the frontend
   service — it is inlined into the client bundle at build time.
4. Smoke-test the deployed URLs the same way stage 3 does: `/health` on the
   backend, `/` on the frontend.

See `DEPLOY.md` for the service topology, variables and cross-origin cookie
notes. Once Railway is fully provisioned this becomes stage 6 — a real deploy
verification after the push — rather than a manual checklist.
