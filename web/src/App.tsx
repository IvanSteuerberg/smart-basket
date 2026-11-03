import { useCallback, useEffect, useState } from "react";
import { getHealth, type Health } from "./api";

type State =
  | { kind: "loading" }
  | { kind: "ready"; health: Health }
  | { kind: "error"; message: string };

export default function App() {
  const [state, setState] = useState<State>({ kind: "loading" });

  const check = useCallback((signal?: AbortSignal) => {
    setState({ kind: "loading" });
    getHealth(signal)
      .then((health) => setState({ kind: "ready", health }))
      .catch((error: unknown) => {
        if (signal?.aborted) return;
        setState({ kind: "error", message: error instanceof Error ? error.message : String(error) });
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    check(controller.signal);
    return () => controller.abort();
  }, [check]);

  return (
    <main className="page">
      <header className="hero">
        <img src="/favicon.svg" alt="" width={56} height={56} />
        <div>
          <h1>Smart Basket</h1>
          <p>Tu cesta de la compra más barata en León, con el menor tiempo de desplazamiento.</p>
        </div>
      </header>

      <section className="card" aria-live="polite">
        <h2>Estado del sistema</h2>
        {state.kind === "loading" && <p className="muted">Comprobando…</p>}
        {state.kind === "error" && (
          <p className="status status-bad">No se puede contactar con el servidor ({state.message}).</p>
        )}
        {state.kind === "ready" && (
          <dl className="status-list">
            <div>
              <dt>Servidor</dt>
              <dd className={state.health.status === "ok" ? "status status-ok" : "status status-bad"}>
                {state.health.status === "ok" ? "Funcionando" : "Con problemas"}
              </dd>
            </div>
            <div>
              <dt>Base de datos</dt>
              <dd className={state.health.database === "ok" ? "status status-ok" : "status status-bad"}>
                {state.health.database === "ok" ? "Disponible" : "No disponible"}
              </dd>
            </div>
            <div>
              <dt>Versión</dt>
              <dd>
                {state.health.version} · {state.health.engine_version}
              </dd>
            </div>
          </dl>
        )}
        <button type="button" onClick={() => check()}>
          Volver a comprobar
        </button>
      </section>

      <section className="card">
        <h2>Próximamente</h2>
        <p className="muted">
          Escribe tu lista de la compra y te diremos qué comprar en cada supermercado, cuánto
          ahorras y en qué orden visitarlos.
        </p>
      </section>
    </main>
  );
}
