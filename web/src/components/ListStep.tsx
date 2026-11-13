import { searchProducts, type SearchResult, type SectionCategory } from "../api";
import { draftFromSearchResult, type DraftItem } from "../draft";
import type { SavedList } from "../storage";
import { PRODUCT_SEARCH_PLACEHOLDER } from "../texts";
import { CategoryTree } from "./CategoryTree";
import { SearchBox } from "./SearchBox";

const LIST_PLACEHOLDER =
  "Escribe tu lista, un producto por línea. Por ejemplo:\n" +
  "2 l de leche semidesnatada\npan de molde\n1 kg de manzanas";

export interface ListStepProps {
  text: string;
  onTextChange: (value: string) => void;
  addedItems: DraftItem[];
  onAddItem: (item: DraftItem) => void;
  onRemoveItem: (id: string) => void;
  sections: SectionCategory[];
  categoriesError: string | null;
  onInterpret: () => void;
  interpreting: boolean;
  interpretError: string | null;
  lists: SavedList[];
  onSaveList: (name: string) => void;
  onLoadList: (id: string) => void;
}

export function ListStep({
  text,
  onTextChange,
  addedItems,
  onAddItem,
  onRemoveItem,
  sections,
  categoriesError,
  onInterpret,
  interpreting,
  interpretError,
  lists,
  onSaveList,
  onLoadList,
}: ListStepProps) {
  function saveList() {
    const name = window.prompt("Nombre de la lista");
    if (name === null) return;
    const trimmed = name.trim();
    if (trimmed === "") return;
    onSaveList(trimmed);
  }

  return (
    <>
      <section className="card">
        <h2>Tu lista de la compra</h2>
        <textarea
          className="list-input"
          value={text}
          placeholder={LIST_PLACEHOLDER}
          aria-label="Tu lista de la compra"
          rows={5}
          onChange={(event) => onTextChange(event.target.value)}
        />
        <button
          type="button"
          onClick={onInterpret}
          disabled={interpreting || (text.trim() === "" && addedItems.length === 0)}
        >
          Interpretar
        </button>
        {interpreting && (
          <p className="muted" role="status">
            Interpretando…
          </p>
        )}
        {interpretError && (
          <p className="error" role="alert">
            {interpretError}
          </p>
        )}
        <div className="saved-lists">
          <button type="button" className="secondary" onClick={saveList}>
            Guardar lista
          </button>
          <select
            aria-label="Mis listas"
            value=""
            disabled={lists.length === 0}
            onChange={(event) => {
              const id = event.target.value;
              if (id) onLoadList(id);
            }}
          >
            <option value="">Mis listas</option>
            {lists.map((list) => (
              <option key={list.id} value={list.id}>
                {list.name}
              </option>
            ))}
          </select>
        </div>
      </section>

      <section className="card">
        <h2>Añadir desde el catálogo</h2>
        <SearchBox<SearchResult>
          placeholder={PRODUCT_SEARCH_PLACEHOLDER}
          search={searchProducts}
          labelOf={(result) => result.name}
          keyOf={(result) => result.key}
          hintOf={(result) => result.path}
          onSelect={(result) => onAddItem(draftFromSearchResult(result))}
        />
        {addedItems.length > 0 && (
          <ul className="added-list">
            {addedItems.map((item) => (
              <li key={item.id}>
                <span>{item.text}</span>
                <button
                  type="button"
                  className="link-button"
                  onClick={() => onRemoveItem(item.id)}
                >
                  Quitar
                </button>
              </li>
            ))}
          </ul>
        )}
        {categoriesError && (
          <p className="error" role="alert">
            {categoriesError}
          </p>
        )}
        <CategoryTree
          sections={sections}
          onPick={(leaf) =>
            onAddItem(
              draftFromSearchResult({ key: leaf.key, name: leaf.name, kind: "leaf", path: "" }),
            )
          }
        />
      </section>
    </>
  );
}
