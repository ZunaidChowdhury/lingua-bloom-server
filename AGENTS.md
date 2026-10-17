# AGENTS.md: LinguaBloom Agent Rules

This file is the single source of rules for any coding agent working on LinguaBloom. The agent is started from the **backend repository** and works on **both repositories**. Read this file fully before every session.

---

## 0. Absolute Rules (never break these)

### 0.1 Git is read-only for the agent
**Never commit. Never push. Never change git state in any way.**

- Forbidden: `git commit`, `git push`, `git add`, `git pull`, `git fetch`, `git merge`, `git rebase`, `git reset`, `git checkout`, `git switch`, `git restore`, `git stash`, `git tag`, `git cherry-pick`, `git revert`, `git rm`, `git mv`, `git clean`, `git init`, `git remote`, `git config`, the `gh` CLI for pushing or creating pull requests, and any script, hook, or API call that does the equivalent.
- Forbidden: editing anything inside a `.git` directory.
- Allowed (read-only inspection only): `git status`, `git diff`, `git log`, `git show`, `git branch --list`, `git ls-files`.
- At the end of each task, **propose one commit message** in the form `TASK-XXX-NN: short summary` and stop. The developer reviews the changes and commits and pushes manually.
- If a task, document, or instruction says to commit or push (for example "green on first push"), do not do it. Tell the developer what to commit or push and why.
- If the developer explicitly asks in chat to run a git write command, ask them to run it themselves.

### 0.2 Secrets
- Never print, echo, log, or paste the value of `GROQ_API_KEY`, `DATABASE_URL`, `TEST_DATABASE_URL`, or any token. Refer to them by name only.
- Never write a real secret into any tracked file, test, fixture, README, or document. Only `.env.example` (empty values) is tracked.
- Never read a `.env` file to display it. Application code may load it at runtime.
- The frontend may only expose `NEXT_PUBLIC_API_URL`. Nothing secret may use a `NEXT_PUBLIC_` prefix.

### 0.3 Honesty
- Never claim a test, build, deployment, or latency figure succeeded unless the command was actually run and its output was seen in this session.
- If a command fails or cannot run (missing credential, no network access), say so plainly and name what is needed.
- Never invent credentials, URLs, measurements, or content. Ask the developer instead.

### 0.4 Scope
- Do only the task requested. Do not start the next task unless the instruction names a range.
- Do not add features, libraries, or files beyond what the task and its acceptance criteria require.
- If something in a document looks wrong or conflicts, stop and ask. Do not silently choose.

---

## 1. Project Summary

**LinguaBloom** (*Little words. Big worlds.*) is an AI-powered English-learning chatbot for children under 7. It is a technical assessment for an AI Full-Stack Engineer position.

**Deadline:** Sunday, 18 October 2026, 08:00 Bangladesh time.

**Assessment requirements (all mandatory):**
1. Progressive learning across three levels (L1, L2, L3).
2. Child mode detection across four modes (Learning, Conversation, Engagement, Support). The bot must not teach in every interaction.
3. Age-appropriate social and emotional learning (SEL).
4. Context-aware responses using level, history, and conversation.
5. End-to-end response latency under 2 seconds.
6. Deliverables: live URL (not localhost), source code, architecture diagram, system design document, README with setup and deployment, English video of at most 2 minutes, GitHub collaborators `farzana@sharif.com` and `masrur@sharif.com`.

---

## 2. Repositories and Locations

| Repo | Role | Local path | Remote |
|---|---|---|---|
| `lingua-bloom-server` | Backend (FastAPI). **The agent starts here** | `C:\Users\Junaid\Documents\GitHub\lingua-bloom-server` | https://github.com/ZunaidChowdhury/lingua-bloom-server |
| `lingua-bloom` | Frontend (Next.js) | `C:\Users\Junaid\Documents\GitHub\lingua-bloom` | https://github.com/ZunaidChowdhury/lingua-bloom |

- From the backend, the frontend is the sibling folder `..\lingua-bloom`.
- Run each command inside the correct repository. Backend tasks run in the backend folder. Frontend tasks run in the frontend folder. State which folder a command ran in when reporting results.
- The developer's machine is **Windows**. Use commands that work in PowerShell. Do not use bash-only syntax. Use `.venv\Scripts\python` for the backend virtual environment, and `npm` for the frontend.

---

## 3. Engineering Files (outside both repositories)

The planning documents are **not** in either repository. They live here:

`ENG = C:\Users\Junaid\Desktop\shared-with-ai\lingua-bloom\Engineering`

| Path under `ENG` | Purpose | Agent access |
|---|---|---|
| `STATE.md` | Task checklist, dependencies, **Current Session State** (about 2.5k tokens) | Read at session start. **The only file the agent may edit** |
| `split\bundles\TASK-XXX-NN.md` | One task, its dependencies, and only the PRD and ARCHITECTURE parts it references | Read for the task being executed |
| `split\arch\NN-*.md`, `split\prd\NN-*.md` | One file per ARCHITECTURE or PRD section | Read only when a bundle is not enough |
| `split\MAP.md` | Index of the split files with token sizes | Read only when looking for a section |
| `PRD.md`, `ARCHITECTURE.md`, `TASKS.md` | Full originals | **Do not read.** They cost about 35k tokens. Use `split\` instead |

**Token budget rules (the context window is small):**
- Never read `PRD.md`, `ARCHITECTURE.md`, or `TASKS.md` in full. Never read more than one bundle at a time.
- Do not re-read a bundle or section already read in this session.
- For `STATE.md`, change a single line with a targeted edit. Never rewrite the whole file.
- Prefer reading a specific line range of a file over reading the whole file.

**Keep the engineering files out of the repositories:**
- Never copy, move, or write any file from `ENG` into either repository.
- Never mention `ENG`, `STATE.md`, `PRD.md`, `TASKS.md`, task IDs, or this file in any tracked file (code comments, README, docs, `.gitignore`, CI, commit messages). Commit messages use the `TASK-XXX-NN` form only because the developer chooses to keep them.
- If a task says to commit `PRD.md`, `ARCHITECTURE.md`, or `TASKS.md` into `docs/` or to link them from a README, do not do it. Tell the developer. The developer decides which design content is published as the system design deliverable.
- Files created by tasks that are internal only (`docs/AC_TRACEABILITY.md`, `docs/SUBMISSION_CHECKLIST.md`) are written to `ENG\work\` instead of the repository.
- Deliverable files (README, `docs/architecture.*`, `docs/latency-report.md`, `docs/contrast-report.md`) are written to the repositories as the task says.
- If the splitter output looks stale or a bundle is missing, tell the developer to run `python splitter.py` in `ENG`. The agent never edits `split\` files.

**Precedence when documents disagree:** this `AGENTS.md` (rules) first, then the task bundle for what to do now, then the ARCHITECTURE sections for how, then the PRD sections for why. Report any conflict to the developer.

---

## 4. Working Protocol

The developer will command tasks by ID, for example `Execute TASK-DOM-03`.

For every task:
1. Read this file and `ENG\STATE.md`. Then read only `ENG\split\bundles\<TASK-ID>.md`.
2. Confirm every dependency is `[x]` in `STATE.md`. If not, stop and tell the developer.
3. Set the task line in `STATE.md` to `[/]` and update **Current Session State** there.
4. If the task says **Developer Action Required** (`DEV` in `STATE.md`), ask for exactly what is listed and wait. Do not guess values.
5. Implement the task. Keep changes small and focused. If the bundle lacks needed detail, read the specific `split\arch` or `split\prd` section file, not the originals.
6. Run the checks required by the acceptance criteria and the Definition of Done (section 8). Read the real output.
7. Set the task line to `[x]` only when every acceptance criteria line is met. Update **Current Session State**. If anything is unmet, leave it `[/]` and explain.
8. Reply using the report format below, including a proposed commit message. **Do not run git commands that change anything.**

**Report format after each task:**
- Task ID and one-line result
- Repository and files created or changed
- Commands run and their outcome (pass or fail, with key output)
- Acceptance criteria checklist (each line marked met or not met)
- Anything the developer must do next
- Proposed commit message: `TASK-XXX-NN: short summary`

Work on one task at a time. Prefer several small verified steps over one large unverified change.

---

## 5. Technology Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js (App Router), React, TypeScript (`strict`), Tailwind CSS v4, shadcn/ui, `next-themes`, Vitest |
| Backend | Python 3.12, FastAPI, Pydantic v2, `pydantic-settings`, Uvicorn (single worker) |
| LLM | Official Groq Python SDK (`AsyncGroq`). No LangChain |
| Database | Supabase PostgreSQL via the transaction pooler, `asyncpg`, plain SQL migrations |
| Testing | pytest, pytest-asyncio, httpx |
| Hosting | Frontend on Vercel, Backend on Render (free tier, Singapore), Database on Supabase (Singapore) |

**Do not add:** LangChain, multi-agent systems, vector databases, voice features, fine-tuning, ORMs, Redis, authentication providers, or analytics tools. Any new dependency needs the developer's approval and a reason.

---

## 6. Architecture Rules

1. **Hybrid design.** Python decides: scoring, answer checking, progression, mode rules, pacing, validation, safety. The LLM only writes warm wording inside those guardrails. Scoring and progression must never depend on the LLM.
2. **Pure domain core.** Code in `app/domain` is pure: no I/O and no imports from `fastapi`, `asyncpg`, or `groq`. It is fully unit tested.
3. **One LLM call per turn.** The single structured call returns `reply`, `suggested_mode`, `confidence`, and `mood`. Hard timeout `LLM_TIMEOUT_S` (default 1.5 seconds). No retries. On timeout, error, invalid JSON, or unsafe output, return a Python fallback template with HTTP 200 and `fallback: true`.
4. **The LLM never writes quiz questions or answer keys.** Python attaches the canonical item from the curriculum bank. The answer key, accepted words, rubric, and reveal text never leave the server.
5. **No demotion.** A single mistake never lowers the level. Only the first attempt on an item exposure counts toward progression.
6. **Pacing.** No more than 3 consecutive Learning turns unless the child explicitly asks to learn or quiz.
7. **Privacy.** Anonymous sessions with an opaque token (`secrets.token_urlsafe(32)`, SHA-256 hashed in the database). No names, emails, or locations. Never log child message text.
8. **Browser calls FastAPI directly.** No Next.js proxy for chat. CORS allows only the exact `FRONTEND_ORIGIN`.
9. **Single instance.** One Uvicorn worker. Per-session locks and rate limits are in memory.
10. **Persistence.** One transaction per turn. Parameterised SQL only. Same-region database and backend (Singapore).
11. **Rendering.** Landing, grown-ups, and start pages are static. `/chat` is client rendered. No ISR.
12. **Mood is uncertain.** Treat mood detection as a guess, never a diagnosis. The bot never labels a child.

---

## 7. Coding Standards

### Backend
- Type hints everywhere. `mypy app` passes. `ruff check .` passes. Domain modules use strict typing.
- Pydantic v2 models for every request and response. Validate at the edge.
- Error body is always `{ "error": { "code": "...", "message": "..." } }` with accurate status codes: 401 invalid or missing token, 403 forbidden, 404 not found, 422 invalid input, 429 rate limited (with `Retry-After`), 503 dependency unavailable, 500 unexpected. Messages are child-safe and never expose internals.
- Async code for I/O. No blocking calls in request handlers.
- Configuration comes only from `Settings`. No hardcoded thresholds, URLs, or keys.
- Tests accompany every task. Use `FakeLLM` and in-memory repositories so tests need no network. Mark real-service tests `@pytest.mark.integration`.

### Frontend
- TypeScript `strict`. No `any`. ESLint including `jsx-a11y` must pass.
- Data layer: one shared fetch layer in `lib/core/api-client.ts` (`apiGet`, `apiMutate`). Read calls in `lib/api/`. Mutation calls in `lib/actions/`. Components never call `fetch` directly.
- Required files and states: `loading.tsx` (themed animation), `error.tsx` rendering `ErrorFallback`, `not-found.tsx` rendering `NotFound`, and a `DataLoadFailed` placeholder when data is empty or fails. Handle 401, 403, and 429 with friendly messages.
- **No placeholder, dummy, or lorem content anywhere.**
- Light and dark themes using the design tokens below. Mobile-first, responsive at 360, 768, and 1280 px. Touch targets at least 44 px. WCAG AA contrast. Respect `prefers-reduced-motion`.
- Consistent style: botanical storybook look, rounded cards, generous spacing.

### Design tokens

| Token | Light | Dark |
|---|---|---|
| Primary green | `#389B78` | `#75D6A8` |
| Page background | `#FFF9EF` | `#101A17` |
| Card | `#FFFFFF` | `#192621` |
| Primary text | `#20332B` | `#F1F7F2` |
| Secondary text | `#52665B` | `#C1D0C6` |
| Border | `#DCE7DF` | `#34483D` |
| Soft mint | `#DDF4E8` | `#203F35` |
| Sky blue | `#8CCFF0` | `#82C9F0` |
| Sunshine yellow | `#FFD76A` | `#F4CF68` |
| Lavender | `#C8B9F2` | `#B9A6F5` |

Mode accents: Learning green, Conversation blue, Engagement yellow, Support lavender. Level accents: L1 mint, L2 blue, L3 lavender.

---

## 8. Commands and Definition of Done

| Check | Backend (run in `lingua-bloom-server`) | Frontend (run in `lingua-bloom`) |
|---|---|---|
| Install | `python -m venv .venv`, then `.venv\Scripts\python -m pip install -r requirements.txt` | `npm install` |
| Lint | `.venv\Scripts\python -m ruff check .` | `npm run lint` |
| Types | `.venv\Scripts\python -m mypy app` | `npx tsc --noEmit` |
| Tests | `.venv\Scripts\python -m pytest -m "not integration"` | `npm test` (once Vitest exists) |
| Build | not applicable | `npm run build` |
| Run | `.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000` | `npm run dev` |

A task is done only when:
- Every acceptance criteria line in the task bundle is met.
- The relevant lint, type, test, and build commands above pass, and the output was actually read.
- No secret is present in any file, log, or output.
- No placeholder or dummy content exists in shipped screens.
- The task line and **Current Session State** in `ENG\STATE.md` are updated.

---

## 9. Developer-Only Actions

The agent must stop and ask for the developer when a task needs any of the following:
- Creating accounts or projects (Supabase, Groq, Render, Vercel, uptime monitor).
- Providing or changing environment values and secrets.
- Running migrations against the real database or running anything against production.
- Deploying, redeploying, or changing hosting settings.
- Reviewing curriculum content, testing on a real phone, recording the video, adding GitHub collaborators, or sending the submission email.
- **Any git commit or push.**

---

## 10. Safety and Content Rules for the Product

- The bot speaks in very short, simple, kind sentences suited to under-7s, with limits per level (L1 up to 6 words per sentence, L2 up to 8, L3 up to 12).
- Never say a child is "wrong". Use effort-based, encouraging language.
- Never ask for or store personal information. Redact emails, phone numbers, and address-like text before storage and before the LLM.
- Child text sent to the LLM is wrapped in delimiters and treated as untrusted data. Ignore any instruction inside it.
- Support mode never includes a quiz. Serious distress gets a deterministic message encouraging the child to talk to a trusted grown-up, with no LLM call.
- Every fallback template must pass the output safety filter.

---

## 11. Cross-Repository Notes

- The API contract in ARCHITECTURE section 8 (`ENG\split\arch\08-*.md`) is the single contract between the repos. When a backend schema changes, update `lib/types.ts` in the frontend in the same task or flag it for the next task.
- Environment variables:
  - Backend: `GROQ_API_KEY`, `GROQ_MODEL`, `DATABASE_URL`, `FRONTEND_ORIGIN`, `LLM_TIMEOUT_S`, optional `TEST_DATABASE_URL`, `LOG_LEVEL`, `ADMIN_KEY`.
  - Frontend: `NEXT_PUBLIC_API_URL` only.
- Local development ports: backend `8000`, frontend `3000`.

---

## 12. Implementation Plan Pattern

When the developer asks for an implementation plan, write one markdown file per task in `ENG\Implementation-Plans\` named `#<n> IP - [TASK-XXX-NN].md`, using this exact section pattern:

**Filename and serialization:**
- Pattern: `#N IP - [TASK-XXX-NN].md` where `N` is a serialized counter shared by all plans in the folder (example: `#1 IP - [TASK-ENV-01].md`).
- Before creating any plan, list `ENG\Implementation-Plans\` and find the highest existing `#N`.
- New files start at `N+1`, assigned in the order the developer named the tasks. Example: developer says *"create plan for TASK-ENV-01, TASK-ENV-02"*, last file is `#1` → create `#2 IP - [TASK-ENV-01].md`, then `#3 IP - [TASK-ENV-02].md`.
- Never reuse, renumber, or overwrite an existing plan file.

````markdown
# Implementation Plan — [TASK-XXX-NN] Short title

Status: Draft (awaiting developer decisions) | Ready
Repo: `<lingua-bloom-server path>` and/or `<lingua-bloom path>` (only the repos involved)
Current state: <1-3 lines: what exists right now — files, versions, what is missing>

## 1. Summary

<2-4 sentences: what the task will accomplish, and what is explicitly out of scope.>

## 2. Steps

### 2.1 <First step title>

<Step instructions. Use a table when presenting choices or decisions.>

```text
<code snippet: exact file content, command, SQL, or config to write>
```

### 2.2 <Next step title>

<More steps, each as 2.x with its own snippet.>

### 2.N Verify

```text
<commands to run — one block, correct for Windows, run in the right repo>
```

Manual checks:
- <checks no command can cover>

## 3. Acceptance Criteria Checklist

- [ ] <one line per acceptance criterion in the task bundle>
````

Rules:
- Steps are numbered `2.1`, `2.2`, … and the **last step is always `Verify`** with runnable commands plus a `Manual checks` list.
- Every file edit, config, or command in a step appears as a copy-pasteable code snippet — no prose-only instructions.
- A step needing developer input is marked **DEV ACTION** and carries a `Blocking rule: do not proceed until the developer supplies the values. Do not guess.`
- The Acceptance Criteria Checklist maps 1:1 to the task bundle's acceptance criteria.
- The plan is written **before** implementation; then follow it step by step, run the Verify commands, and read the real output.
- Plans contain no secrets and are never committed into either repository.
