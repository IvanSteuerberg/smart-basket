# Instructions for AI agents

Guidance for any AI assistant (Claude, Gemini, DeepSeek, Copilot…) working in this repository. General project context lives in [README.md](README.md) and `docs/idea-base/idea.tex`.

## Language

- Code, identifiers, comments, commit messages and repository docs (README, this file) in **English**.
- The academic documents under `docs/` (concept document and prompt log) stay in **Spanish**.
- Talk to the author in Spanish.

## Session routine

The author works from several computers, and documents edited outside the repo have drifted before. The repo is the single source of truth.

1. **Start:** `git pull`. Read `knowledge/index.md` and the current week in the activity log ("Planificado para el resto de la semana") to see where things stand.
2. **During:** when a session produces a decision or finding worth recording, offer a prompt log entry with two sources (see below).
3. **End:** add the session's activities to the activity log; record knowledge changes in `knowledge/log.md`; update `scripts/osf_index.json` if documents or pending assignments changed. Then ask the author before committing, pushing and publishing to OSF.
4. **Pace:** the author spreads work across days so the weekly activity log reflects real progress. Propose what to do next day by day instead of chaining many phases in one session.

## Current phase

- The project is in **design phase**: no code yet.
- Do not assume a technology (database, framework, language) is chosen unless it is recorded as a decision in `knowledge/decisions/`.
- Always favor a scoped **MVP** that can be justified in the academic context.

## Knowledge base (`knowledge/`)

Engineering knowledge (vision, requirements, architecture, decisions, glossary) lives in `knowledge/`, an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format) v0.2 bundle. Read `knowledge/index.md` first.

- One concept per file, with YAML frontmatter. `type` is required; also set `title`, `description`, `tags`, `status` (`draft` | `stable` | `deprecated`) and `generated: { by, at }` (ISO 8601 with UTC offset).
- Actors: agents as `<producer>/<version>` (e.g. `claude-code/claude-opus-5-5`); the author as `human:IvanSteuerberg`. Only the author adds `verified` entries.
- Decisions go in `knowledge/decisions/NNNN-short-title.md` (`type: Architecture Decision`) with Context, Decision, Consequences and, when relevant, Revisit when. Cite the prompt log entry they come from in `sources`.
- Links are bundle-root-relative (`/decisions/0001-...md`).
- Every change gets a bullet in `knowledge/log.md` under a `YYYY-MM-DD` heading (newest first), and new concepts are listed in `knowledge/index.md`.
- The bundle is in English. The academic documents in `docs/` stay in Spanish and narrate how decisions were reached; the bundle states what was decided.

## Prompt log (memoria de prompts)

Use of generative AI in the project is documented in `docs/memoria-prompts/`. It is a graded deliverable.

- Each month has its own file at `docs/memoria-prompts/entradas/<mes>.tex`, included via `\input` from `memoria-prompts.tex` (uncomment the line when starting a new month).
- Each relevant interaction is a `\subsection{Señal de Tiempo N: <tema>}` with this structure:
  1. **Fecha**, **Asistente Virtual Utilizado** and **Objetivo**.
  2. A `tcolorbox` *Prompt Introducido* (`colback=promptcolor`).
  3. One *Insights de <asistente>* box per AI consulted (`colback=responsecolor`): an own summary, not a verbatim copy.
  4. A **Decisión de Ingeniería / Aplicación al Proyecto** paragraph.
- "Señal de Tiempo" numbering continues across months. Check the last number in the latest month file before adding one.
- **Two sources per entry.** Write a self-contained prompt (the second AI has no session context) and send the same prompt to Gemini through Antigravity CLI, run from an empty temporary folder so it cannot touch the repo: `agy -p "<prompt>" --model gemini-3.8-flash-high --disable-slash-commands`. On the author's main Windows machine the binary is `%LOCALAPPDATA%\agy\bin\agy.exe`; `agy models` lists the models. Save the raw answer with the prompt in `docs/memoria-prompts/fuentes/YYYY-MM-DD-stN-gemini.md` and summarize it in its own *Insights de Gemini* box. State in the entry that the agent in the session answered with project context and Gemini without it.
- When a working session with an agent produces a relevant decision or finding, offer the author to draft the matching entry.
- If an AI answer already recorded contains an incorrect or unverified claim, point it out instead of taking it for granted.

## Activity log (registro de actividad)

`docs/registro-actividad/registro-actividad.tex` records all course work week by week (Monday to Sunday) and is published to OSF.

- After any session that produces work, add one `\actividad{Tipo}{Descripción}{Resultado}` per activity under the day's `\subsection*{<Weekday> <d> de <mes>}`, inside the current week's `\section*{Semana N: <range>}`. Types: Clase, Tarea, Investigación, Decisión, Documentación, Análisis, Visita.
- Keep it high level and point to the artifact (Señal de Tiempo, decision number, file) instead of repeating its content.
- The current week ends with "Planificado para el resto de la semana". When a week closes, write its one-line `\textit{Resumen:}`, remove the plan, and open the next week. Assignments not yet done stay in "Encargos pendientes".

## Publishing to OSF

The author's OSF project (`ysmkz`, private, shared with the professor) receives the compiled PDFs. `python scripts/osf_publish.py` shows what would change; `--apply` compiles and uploads. Documents keep a fixed name in OSF, which stores every upload as a new version, so never create dated copies. After publishing or moving files, regenerate the index on the wiki home page with `python scripts/osf_index.py --apply`; descriptions, statuses and pending assignments live in `scripts/osf_index.json` (Spanish, keep it current). OSF folders: `01-proyecto`, `02-informes`, `03-lecturas`, `04-referencias`, `05-notas-de-clase` (`dd-mm-yyyy.txt`), `06-guias`, `99-archivo`. New documents to publish are added to `DOCUMENTS` in `scripts/osf_publish.py` (`.tex` sources are compiled to PDF; other files are uploaded as they are). Only publish with the author's go-ahead. The token lives in `.env` (`OSF_TOKEN`, git-ignored): never print or commit it.

## LaTeX

- Build from each document's folder (`\input` paths are relative).
- Build outputs (PDFs and auxiliary files) are not versioned; see `.gitignore`.

## Git

- Do not commit or push unless the author asks. Pushing matters: other computers only see what is on GitHub.
- Short, imperative commit messages in English ("Add…", "Fix…").
