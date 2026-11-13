import type { LatLon, Recommendation } from "../api";
import { formatAmount, formatDateTime, formatEuro, formatQuantity } from "../format";
import { MapView } from "./MapView";

export interface BasketStepProps {
  recommendation: Recommendation;
  origin: LatLon | null;
  onBack: () => void;
  onNewList: () => void;
}

export function BasketStep({ recommendation, origin, onBack, onNewList }: BasketStepProps) {
  const stores = [...recommendation.stores].sort((a, b) => a.position - b.position);

  return (
    <section className="card">
      <h2>Tu cesta</h2>

      <p className="explanation">{recommendation.explanation}</p>

      <div className="basket-summary">
        <strong>Total: {formatEuro(recommendation.total_cost)}</strong>
        <span className="muted">{recommendation.minutes} min de trayecto</span>
      </div>

      <ol className="store-list">
        {stores.map((store) => (
          <li key={store.store_id}>
            <article className="store-card">
              <h3>
                {store.position}. {store.chain} – {store.name}
              </h3>
              <ul className="basket-lines">
                {store.lines.map((line, index) => (
                  <li key={`${line.text}-${index}`} className="basket-line">
                    <div>
                      <p className="basket-line-name">{line.product_name}</p>
                      <p className="small muted">
                        {line.packs} packs · {formatQuantity(line.quantity_bought)}
                      </p>
                    </div>
                    <span className="basket-line-cost">{formatEuro(line.cost)}</span>
                  </li>
                ))}
              </ul>
              <div className="subtotal">
                <span>Subtotal</span>
                <span>{formatEuro(store.subtotal)}</span>
              </div>
            </article>
          </li>
        ))}
      </ol>

      {recommendation.missing.length > 0 && (
        <div className="missing">
          <h3>No incluido</h3>
          <ul>
            {recommendation.missing.map((missing, index) => (
              <li key={`${missing.text}-${index}`}>
                <span>{missing.text}</span>
                {missing.reason === "separate_stop" && missing.stop && (
                  <span className="small muted">
                    {" "}
                    Está en {missing.stop.name}, {formatAmount(missing.stop.cost)} €,{" "}
                    {missing.stop.extra_minutes} min más
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <MapView origin={origin} stores={stores} route={recommendation.route} fitContent />

      <p className="small muted">Precios del {formatDateTime(recommendation.data_as_of)}</p>

      <div className="actions">
        <button type="button" className="secondary" onClick={onBack}>
          Cambiar opciones
        </button>
        <button type="button" onClick={onNewList}>
          Nueva lista
        </button>
      </div>
    </section>
  );
}
