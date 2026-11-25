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
  /** Text to show in the field, e.g. the address already chosen; typing still edits it. */
  value?: string;
  /** After a pick, keep its label in the field instead of clearing it. */
  keepSelection?: boolean;
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
  value,
  keepSelection = false,
}: SearchBoxProps<T>) {
  const [query, setQuery] = useState(value ?? "");
  const [results, setResults] = useState<T[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const controller = useRef<AbortController | null>(null);
  // The label of the item just picked: it is shown, not searched again.
  const pickedRef = useRef<string | null>(value ?? null);

  useEffect(() => {
    if (value === undefined) return;
    pickedRef.current = value;
    setQuery(value);
    setResults([]);
  }, [value]);

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
    if (trimmed.length < minLength || trimmed === pickedRef.current) {
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
    const label = labelOf(item);
    pickedRef.current = keepSelection ? label : null;
    setQuery(keepSelection ? label : "");
    setResults([]);
    setError(null);
    setSearching(false);
    onSelect(item);
  }

  const tooShort = query.trim().length < minLength;

  return (
    <form className="relative grid gap-1.5" onSubmit={submit}>
      <div className="flex gap-2">
        <input
          type="search"
          value={query}
          placeholder={placeholder}
          aria-label={placeholder}
          autoComplete="off"
          onChange={(event) => setQuery(event.target.value)}
          className="min-h-11 w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-3 font-sans text-[0.9375rem] text-[var(--ink-primary)] outline-none placeholder:text-[var(--ink-secondary)] focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]"
        />
        {onDemand && (
          <button
            type="submit"
            disabled={tooShort || searching}
            className="min-h-11 shrink-0 rounded-xl bg-[var(--accent-primary)] px-4 text-[0.9375rem] font-bold text-[var(--accent-on-primary)] transition-colors hover:bg-[var(--accent-primary-hover)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            Buscar
          </button>
        )}
      </div>
      {error && (
        <p className="text-[0.8125rem] font-semibold text-[var(--danger-fg)]" role="alert">
          {error}
        </p>
      )}
      {results.length > 0 && (
        <ul className="divide-y divide-[var(--border-subtle)] overflow-hidden rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)]">
          {results.map((item) => (
            <li key={keyOf(item)}>
              <button
                type="button"
                className="flex min-h-11 w-full flex-col justify-center px-3 py-2 text-left text-[0.9375rem] text-[var(--ink-primary)] transition-colors hover:bg-[var(--accent-soft)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--accent-primary)]"
                onClick={() => choose(item)}
              >
                <span>{labelOf(item)}</span>
                {hintOf && (
                  <span className="text-[0.8125rem] text-[var(--ink-secondary)]">{hintOf(item)}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}
