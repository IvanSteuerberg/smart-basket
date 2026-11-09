# Entregas en Smart Basket (recomendador-supermercado)

## Documentación
- Instrucciones para agentes: `AGENTS.md` (y `CLAUDE.md`, que lo incluye). Idioma: código y docs del repo en inglés; `docs/` en español.
- Requisitos, decisiones y evaluación: `knowledge/` (empezar por `knowledge/index.md`); decisiones en `knowledge/decisions/NNNN-*.md`.
- Plan de la semana: `docs/registro-actividad/registro-actividad.tex` («Planificado para la semana»).

## Ramas
- Base `main`. Integración por iteración: `feat/i<N>-<tema>`; entregas `wip/i<N>-eN` en worktrees `../recomendador-supermercado-wt-eN`.
- Integración con `git merge --no-ff`; PR a `main` solo con el OK del autor. La CI de GitHub Actions corre en el PR.

## Comandos
- Pruebas y lint del backend (Docker, Python 3.15 en contenedor; en Windows el `uv` local no instala Python 3.15): `bash scripts/test-backend.sh [--db] [ruta de tests]`.
- `--db` necesita `docker compose up -d db` y una base de pruebas; en paralelo, una por entrega con `TEST_DB_NAME` (p. ej. `smart_basket_test_e2`), porque los tests de migración bajan y suben el esquema.
- Web: `npm ci && npm run typecheck && npm run build` en `web/`.
- Stack completo: `docker compose up -d` (necesita `.env`, git-ignorado, con las contraseñas generadas).

## Reglas que no se rompen
- Datos personales del autor (listas, tiques) nunca en el repo: viven en `C:\Users\Hallo\Documents\Proyectos\smart-basket-private\`.
- Datos recogidos de las cadenas (productos, precios, respuestas en bruto) nunca en el repo (NFR-07); los tests usan JSON sintéticos.
- Dinero siempre `Decimal`; el optimizador y el preprocesador son módulos puros (sin red ni base de datos).
- No tocar `docs/`, `experiments/` ni `scripts/osf_*` desde una entrega; los documentos los actualiza el orquestador.

## Implementadores en este proyecto
- ds (Claude Code nativo + Go): `-PermitidosExtra 'Bash(bash scripts/test-backend.sh:*)'` y `-Variables 'TEST_DB_NAME=smart_basket_test_eN'`.
- agy: `permitidos.json` con el comando exacto `bash scripts/test-backend.sh --db <ruta>` y el `TEST_DB_NAME` en el propio comando no es posible: usar una base por defecto distinta solo si agy corre solo.
- La cuota de agy se consulta desde PowerShell (`agy -p "/usage"`), no desde Git Bash.
