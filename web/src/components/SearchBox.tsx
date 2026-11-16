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
    <form className="relative my-2 grid gap-1.5" onSubmit={submit}>
      <div className="flex gap-2">
        <input
          type="search"
          value={query}
          placeholder={placeholder}
          aria-label={placeholder}
          autoComplete="off"
          onChange={(event) => setQuery(event.target.value)}
          className="w-full rounded-xl border border-stone-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-brand focus:ring-1 focus:ring-brand"
        />
        {onDemand && (
          <button
            type="submit"
            disabled={tooShort || searching}
            className="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-50"
          >
            Buscar
          </button>
        )}
      </div>
      {error && (
        <p className="text-xs font-semibold text-price" role="alert">
          {error}
        </p>
      )}
      {results.length > 0 && (
        <ul className="mt-1 divide-y divide-stone-100 overflow-hidden rounded-xl border border-stone-200 bg-white shadow-sm">
          {results.map((item) => (
            <li key={keyOf(item)}>
              <button
                type="button"
                className="flex w-full flex-col p-2.5 text-left text-sm text-slate-900 transition-colors hover:bg-brand-soft"
                onClick={() => choose(item)}
              >
                <span>{labelOf(item)}</span>
                {hintOf && <span className="text-xs text-stone-500">{hintOf(item)}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}
