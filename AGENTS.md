# Instructions for AI agents

Guidance for any AI assistant (Claude, Gemini, DeepSeek, Copilot…) working in this repository. General project context lives in [README.md](README.md) and `docs/idea-base/idea.tex`.

## Language

- Code, identifiers, comments, commit messages and repository docs (README, this file) in **English**.
- The academic documents under `docs/` (concept document and prompt log) stay in **Spanish**.
- Talk to the author in Spanish.

## Current phase

- The project is in **concept phase**: no tech stack has been chosen.
- Do not assume a technology (database, framework, language) is chosen unless it is recorded in a "Decisión de Ingeniería" in the prompt log.
- Always favor a scoped **MVP** that can be justified in the academic context.

## Prompt log (memoria de prompts)

Use of generative AI in the project is documented in `docs/memoria-prompts/`. It is a graded deliverable.

- Each month has its own file at `docs/memoria-prompts/entradas/<mes>.tex`, included via `\input` from `memoria-prompts.tex` (uncomment the line when starting a new month).
- Each relevant interaction is a `\subsection{Señal de Tiempo N: <tema>}` with this structure:
  1. **Fecha**, **Asistente Virtual Utilizado** and **Objetivo**.
  2. A `tcolorbox` *Prompt Introducido* (`colback=promptcolor`).
  3. One *Insights de <asistente>* box per AI consulted (`colback=responsecolor`): an own summary, not a verbatim copy.
  4. A **Decisión de Ingeniería / Aplicación al Proyecto** paragraph.
- "Señal de Tiempo" numbering continues across months.
- When a working session with an agent produces a relevant decision or finding, offer the author to draft the matching entry.
- If an AI answer already recorded contains an incorrect or unverified claim, point it out instead of taking it for granted.

## LaTeX

- Build from each document's folder (`\input` paths are relative).
- Build outputs (PDFs and auxiliary files) are not versioned; see `.gitignore`.

## Git

- Do not commit or push unless the author asks.
- Short, imperative commit messages in English ("Add…", "Fix…").
