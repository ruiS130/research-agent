# Roadmap

Goal: make this a project someone can open from a link, try in 30 seconds, and understand from the README in under a minute.

The core engineering is in place (LangGraph pipeline, durable SQLite jobs, cost tracking, eval set, tests). What's missing is what an outside viewer sees: a finished report page, recorded eval numbers, CI, and a live deployment.

**If time is short, do these three first:** finish the report page (1), record eval numbers (5), deploy with a spending cap (10, 11).

## Phase 1 — Finish the demo

*Goal: the app looks finished when run locally.*

- [ ] **1. Finish `/report/{id}`** (same id as Chroma `session_id`)
  - [x] Route + placeholder HTML (`static/report.html`)
  - [ ] Fetch job/report JSON from `GET /research/{id}` and/or `GET /history/{id}`
  - [ ] Render markdown with numbered, clickable sources
  - [ ] "Still running" and "not found" states, with a link back to `/`
  - [ ] Copy link and download `.md`
- [ ] **2. Link to it everywhere:** "Open report" button when a job reaches `done`, and links from the history list
- [ ] **3. UI polish:** cleaner layout, a loading state per pipeline step, friendly errors (search failed, missing API key), works on phones
- [ ] **4. Reliable search for demos:** Tavily as the main provider, DuckDuckGo HTML as the fallback

## Phase 2 — Prove it works

*Goal: back up quality and cost with real numbers.*

- [ ] **5. Record eval baselines** for `min` + Haiku and `full` + Sonnet; add a README table with score, cost/job, and time/job
- [ ] **6. Add a Claude-as-judge scorer** that checks whether each cited claim is supported by its source, reported next to the lexical scores
- [ ] **7. Write a short findings note:** cost vs. quality between modes, and which node dominates cost

## Phase 3 — Make it real software

*Goal: safe to put on the public internet.*

- [ ] **8. CI:** GitHub Actions running pytest + ruff on every push, with a README badge
- [ ] **9. Docker:** `Dockerfile` + `docker-compose.yml`, Chroma and SQLite on a volume, one-command start
- [ ] **10. Access control:** access code or API key, per-IP rate limits, hard daily spending cap
- [ ] **11. Deploy** (Fly.io, Railway, or Render) with a persistent volume; live link at the top of the README
- [ ] **12. Background work:** document that FastAPI `BackgroundTasks` assumes a single instance, or move to a small worker queue before scaling out

## Phase 4 — Tell the story

*Goal: someone gets the project in under a minute.*

- [ ] **13. Rework the README:** one-line pitch, live link, and GIF at the top; architecture diagram, eval table, and design decisions (why LangGraph, why `min` vs `full`, how cost is tracked); move the changelog out
- [ ] **14. 2–3 minute demo video:** topic → live steps → report → cost breakdown
- [ ] **15. Repo cleanup:** remove `.DS_Store`, confirm `chroma_data/` and `data/` are gitignored, keep or drop `/do-next`

## Stretch

- [ ] Resume a mid-pipeline LangGraph run after a crash
- [ ] Let users pick the model
- [ ] Compare two reports side by side
- [ ] Export a report as PDF

## Shipped

- [x] SSE progress: `GET /research/{id}/stream`
- [x] Minimal web UI (topic, live steps, report, history)
- [x] Recover completed jobs from Chroma after restart
- [x] `GET /history/{session_id}` full report
- [x] pytest suite with mocked Claude/search
- [x] Optional search provider (Tavily/Serper) fallback
- [x] `/do-next` roadmap page
- [x] Min-cost mode (`COST_MODE=min`, ~1 Haiku call/job)
- [x] Durable SQLite jobs: upsert on every node, interrupt non-terminal jobs on boot, no in-memory `_jobs`
- [x] Observability: JSON logs with `job_id`, per-node timing, per-job token usage and `estimated_usd`, per-call tokens tagged by node, Haiku 5.5 100K long-context flag
- [x] Eval harness: 16 questions scored on facts, citation match, and coverage
