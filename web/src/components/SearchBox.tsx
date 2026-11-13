import { useEffect, useState } from "react";
import { describeError } from "../api";

const DEBOUNCE_MS = 300;

export interface SearchBoxProps<T> {
  placeholder: string;
  search: (query: string, signal: AbortSignal) => Promise<T[]>;
  labelOf: (item: T) => string;
  keyOf: (item: T) => string;
  hintOf?: (item: T) => string;
  onSelect: (item: T) => void;
}

/** Type-ahead field shared by the product catalog and the address search. */
export function SearchBox<T>({
  placeholder,
  search,
  labelOf,
  keyOf,
  hintOf,
  onSelect,
}: SearchBoxProps<T>) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<T[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const trimmed = query.trim();
    setError(null);
    if (trimmed === "") {
      setResults([]);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      search(trimmed, controller.signal)
        .then((found) => {
          if (!controller.signal.aborted) setResults(found);
        })
        .catch((cause: unknown) => {
          if (controller.signal.aborted) return;
          setResults([]);
          setError(describeError(cause));
        });
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, search]);

  function choose(item: T) {
    setQuery("");
    setResults([]);
    setError(null);
    onSelect(item);
  }

  return (
    <div className="search-box">
      <input
        type="search"
        value={query}
        placeholder={placeholder}
        aria-label={placeholder}
        autoComplete="off"
        onChange={(event) => setQuery(event.target.value)}
      />
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {results.length > 0 && (
        <ul className="search-results">
          {results.map((item) => (
            <li key={keyOf(item)}>
              <button type="button" className="search-result" onClick={() => choose(item)}>
                <span>{labelOf(item)}</span>
                {hintOf && <span className="small muted">{hintOf(item)}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
