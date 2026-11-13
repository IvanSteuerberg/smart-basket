import { searchProducts, type SearchResult } from "../api";
import { allResolved, UNITS, type DraftItem } from "../draft";
import { PRODUCT_SEARCH_PLACEHOLDER } from "../texts";
import { SearchBox } from "./SearchBox";

export interface ReviewStepProps {
  items: DraftItem[];
  degraded: boolean;
  onChange: (id: string, patch: Partial<DraftItem>) => void;
  onPickCategory: (id: string, result: SearchResult) => void;
  onRemove: (id: string) => void;
  onBack: () => void;
  onContinue: () => void;
}

export function ReviewStep({
  items,
  degraded,
  onChange,
  onPickCategory,
  onRemove,
  onBack,
  onContinue,
}: ReviewStepProps) {
  return (
    <section className="card">
      <h2>Revisa cómo hemos entendido tu lista</h2>

      {degraded && (
        <p className="banner" role="status">
          Hemos interpretado la lista sin el modelo de lenguaje: revisa las líneas marcadas.
        </p>
      )}

      <ul className="review-list">
        {items.map((item) => (
          <li key={item.id} className="review-item">
            <div className="review-head">
              <span className="review-original">{item.text}</span>
              <button type="button" className="link-button" onClick={() => onRemove(item.id)}>
                Quitar
              </button>
            </div>

            {item.categoryKey === null ? (
              <p className="error">No lo reconocemos: elige un producto</p>
            ) : (
              <p className="review-product">{item.categoryName}</p>
            )}

            <SearchBox<SearchResult>
              placeholder={PRODUCT_SEARCH_PLACEHOLDER}
              search={searchProducts}
              labelOf={(result) => result.name}
              keyOf={(result) => result.key}
              hintOf={(result) => result.path}
              onSelect={(result) => onPickCategory(item.id, result)}
            />

            <div className="review-fields">
              <label className="field">
                <span>Cantidad</span>
                <input
                  inputMode="decimal"
                  value={item.quantity}
                  onChange={(event) => onChange(item.id, { quantity: event.target.value })}
                />
              </label>
              <label className="field">
                <span>Unidad</span>
                <select
                  value={item.unit}
                  onChange={(event) =>
                    onChange(item.id, { unit: event.target.value as DraftItem["unit"] })
                  }
                >
                  {UNITS.map((unit) => (
                    <option key={unit} value={unit}>
                      {unit}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <label className="field">
              <span>Marca</span>
              <input
                value={item.brand}
                placeholder="Cualquier marca"
                onChange={(event) => onChange(item.id, { brand: event.target.value })}
              />
            </label>

            <label className="choice">
              <input
                type="checkbox"
                checked={item.privateLabelOk}
                onChange={(event) => onChange(item.id, { privateLabelOk: event.target.checked })}
              />
              Acepto marca blanca
            </label>
          </li>
        ))}
      </ul>

      <div className="actions">
        <button type="button" className="secondary" onClick={onBack}>
          Volver
        </button>
        <button type="button" onClick={onContinue} disabled={!allResolved(items)}>
          Continuar
        </button>
      </div>
    </section>
  );
}
