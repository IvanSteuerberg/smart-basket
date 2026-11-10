# Deliveries in Smart Basket (recomendador-supermercado)

Project settings for the `entregas` skill (planned iterations split into small deliveries for AI implementers and reviewers).

## Documentation
- Agent instructions: `AGENTS.md` (and `CLAUDE.md`, which includes it). Code and repository docs in English; `docs/` in Spanish.
- Requirements, decisions and evaluation: `knowledge/` (start at `knowledge/index.md`); decisions in `knowledge/decisions/NNNN-*.md`.
- Plan of the week: `docs/registro-actividad/registro-actividad.tex` ("Planificado para la semana").

## Branches
- Base `main`. Integration per iteration: `feat/i<N>-<topic>`; deliveries `wip/i<N>-eN` in worktrees `../recomendador-supermercado-wt-eN`.
- Integrate with `git merge --no-ff`; a pull request to `main` only with the author's approval. GitHub Actions CI runs on the pull request.

## Commands
- Backend tests and lint (Docker, Python 3.15 in a container; on Windows the local `uv` cannot install Python 3.15): `bash scripts/test-backend.sh [--db] [test path]`.
- `--db` needs `docker compose up -d db` and a test database; in parallel, one per delivery with `TEST_DB_NAME` (for example `smart_basket_test_e2`), because the migration tests drop and recreate the schema.
- Web: `npm ci && npm run typecheck && npm run build` in `web/`.
- Whole stack: `docker compose up -d` (needs `.env`, git-ignored, with generated passwords). Manual crawl: `docker compose run --rm worker smart-basket-ingest mercadona`.

## Rules that are never broken
- The author's personal data (shopping lists, receipts) never goes into the repository; it lives in a private folder outside it.
- Collected chain data (products, prices, raw responses) never goes into the repository (NFR-07); tests use synthetic JSON. Chain category trees (codes and names only) are the exception, by decision 0015.
- Money is always `Decimal`; the optimizer and the preprocessor are pure modules (no network or database).
- A delivery does not touch `docs/`, `experiments/` or `scripts/osf_*`; the orchestrator updates the documents.

## Implementers in this project
- ds (native Claude Code with OpenCode Go): `-PermitidosExtra 'Bash(bash scripts/test-backend.sh:*)'` and `-Variables 'TEST_DB_NAME=smart_basket_test_eN'`.
- agy: a `permitidos.json` with the exact command `bash scripts/test-backend.sh --db <path>` (it uses the default test database, so run it alone or give the others their own `TEST_DB_NAME`). It stops if it tries to read a file outside the worktree.
- The agy quota is read from PowerShell (`agy -p "/usage"`), not from Git Bash.
