import { useEffect, useRef, useState, type FormEvent } from "react";
import { describeError } from "../api";

const DEBOUNCE_MS = 300;

export interface SearchBoxProps<T> {
  placeholder: string;
  search: (query: string, signal: AbortSignal) => Promise<T[]>;
  labelOf: (item: T) => string;
  keyOf: (item: T) => string;
  hintOf?: (item: T) => string;
  onSelect: (item: T) => void;
  /** Shortest trimmed query that reaches the API. */
  minLength?: number;
  /** Search only on Enter or the button, never while typing. */
  onDemand?: boolean;
}

/** Search field shared by the product catalog and the address search. */
export function SearchBox<T>({
  placeholder,
  search,
  labelOf,
  keyOf,
  hintOf,
  onSelect,
  minLength = 1,
  onDemand = false,
}: SearchBoxProps<T>) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<T[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const controller = useRef<AbortController | null>(null);

  function searchWith(text: string) {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setError(null);
    setSearching(true);
    search(text, current.signal)
      .then((found) => {
        if (!current.signal.aborted) setResults(found);
      })
      .catch((cause: unknown) => {
        if (current.signal.aborted) return;
        setResults([]);
        setError(describeError(cause));
      })
      .finally(() => {
        if (!current.signal.aborted) setSearching(false);
      });
  }

  useEffect(() => {
    if (onDemand) return;
    const trimmed = query.trim();
    setError(null);
    if (trimmed.length < minLength) {
      controller.current?.abort();
      setResults([]);
      setSearching(false);
      return;
    }
    const timer = setTimeout(() => searchWith(trimmed), DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.current?.abort();
    };
  }, [query, search, minLength, onDemand]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = query.trim();
    if (trimmed.length < minLength || searching) return;
    searchWith(trimmed);
  }

  function choose(item: T) {
    controller.current?.abort();
    setQuery("");
    setResults([]);
    setError(null);
    onSelect(item);
  }

  const tooShort = query.trim().length < minLength;

  return (
    <form className="search-box" onSubmit={submit}>
      <div className="search-row">
        <input
          type="search"
          value={query}
          placeholder={placeholder}
          aria-label={placeholder}
          autoComplete="off"
          onChange={(event) => setQuery(event.target.value)}
        />
        {onDemand && (
          <button type="submit" disabled={tooShort || searching}>
            Buscar
          </button>
        )}
      </div>
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
    </form>
  );
}
