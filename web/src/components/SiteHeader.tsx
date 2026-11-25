import { useEffect, useState, type FormEvent } from "react";
import { HOME_HASH } from "../router";
import { PRODUCT_SEARCH_PLACEHOLDER } from "../texts";
import { useTheme, type ResolvedTheme } from "../theme";

const ICON_PROPS = {
  "aria-hidden": true,
  viewBox: "0 0 24 24",
  className: "h-5 w-5 shrink-0",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

function ListIcon() {
  return (
    <svg {...ICON_PROPS}>
      <path d="M3 4h2l2.2 10.2a1 1 0 0 0 1 .8h8.5a1 1 0 0 0 1-.8L20 7H6" />
      <circle cx="9" cy="19" r="1.4" />
      <circle cx="17" cy="19" r="1.4" />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg {...ICON_PROPS}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg {...ICON_PROPS}>
      <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z" />
    </svg>
  );
}

function SlidersIcon() {
  return (
    <svg {...ICON_PROPS}>
      <path d="M4 7h9M17 7h3M4 17h3M11 17h9" />
      <circle cx="15" cy="7" r="2" />
      <circle cx="9" cy="17" r="2" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg {...ICON_PROPS}>
      <circle cx="11" cy="11" r="6" />
      <path d="m20 20-4.2-4.2" />
    </svg>
  );
}

export const THEME_TO_DARK_LABEL = "Cambiar a modo oscuro";
export const THEME_TO_LIGHT_LABEL = "Cambiar a modo claro";

const CONTROL =
  "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] text-[0.8125rem] font-semibold text-[var(--ink-primary)] transition-colors hover:border-[var(--accent-primary)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)]";

export interface HeaderActionsProps {
  resolvedTheme: ResolvedTheme;
  cartCount: number;
  onToggleTheme: () => void;
  onOpenPreferences: () => void;
  onOpenCart: () => void;
}

/** Theme quick toggle, settings and the list button (no hooks, so it can be tested alone). */
export function HeaderActions({
  resolvedTheme,
  cartCount,
  onToggleTheme,
  onOpenPreferences,
  onOpenCart,
}: HeaderActionsProps) {
  const dark = resolvedTheme === "dark";
  return (
    <div className="ml-auto flex shrink-0 items-center gap-2 min-[540px]:ml-0">
      <button
        type="button"
        onClick={onToggleTheme}
        aria-label={dark ? THEME_TO_LIGHT_LABEL : THEME_TO_DARK_LABEL}
        className={`${CONTROL} min-w-11`}
      >
        {dark ? <SunIcon /> : <MoonIcon />}
      </button>
      <button
        type="button"
        onClick={onOpenPreferences}
        className={`${CONTROL} min-w-11 px-3`}
      >
        <SlidersIcon />
        <span className="sr-only sm:not-sr-only">Ajustes</span>
      </button>
      <button
        type="button"
        onClick={onOpenCart}
        className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-[var(--accent-primary)] px-3 text-[0.8125rem] font-bold whitespace-nowrap text-[var(--accent-on-primary)] transition-colors hover:bg-[var(--accent-primary-hover)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)] min-[540px]:px-4"
      >
        <ListIcon />
        <span className="max-[539px]:sr-only">Tu lista</span>
        <span className="tabular-nums inline-grid h-[1.375rem] min-w-[1.375rem] place-items-center rounded-full bg-[var(--accent-on-primary)] px-1.5 text-[0.8125rem] font-extrabold text-[var(--accent-primary)]">
          {cartCount}
        </span>
      </button>
    </div>
  );
}

export interface SiteHeaderProps {
  cartCount: number;
  /** Query shown in the search field, so suggestions and the page stay in sync. */
  query: string;
  onSearch: (query: string) => void;
  onOpenCart: () => void;
  onOpenPreferences: () => void;
}

/** Wordmark, catalog search, theme toggle, settings and the list button, shared by every page. */
export function SiteHeader({
  cartCount,
  query,
  onSearch,
  onOpenCart,
  onOpenPreferences,
}: SiteHeaderProps) {
  const [value, setValue] = useState(query);
  const { resolved, toggle } = useTheme();

  useEffect(() => {
    setValue(query);
  }, [query]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSearch(value.trim());
  }

  return (
    <header className="sticky top-0 z-40 border-b border-[var(--border-subtle)] bg-[color-mix(in_oklab,var(--surface-canvas)_92%,transparent)] text-[var(--ink-primary)] backdrop-blur">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2.5 min-[540px]:flex-nowrap min-[540px]:gap-4 min-[540px]:px-5">
        <a
          href={HOME_HASH}
          className="flex shrink-0 items-center gap-2 text-xl font-extrabold tracking-tight text-[var(--ink-primary)]"
        >
          <img src="/favicon.svg" alt="" width={30} height={30} />
          <span>Smart Basket</span>
        </a>

        <form
          role="search"
          onSubmit={submit}
          className="relative order-3 min-w-0 basis-full min-[540px]:order-none min-[540px]:flex-1 min-[540px]:basis-auto"
        >
          <input
            type="search"
            value={value}
            placeholder={PRODUCT_SEARCH_PLACEHOLDER}
            aria-label="Buscar en el catálogo"
            autoComplete="off"
            enterKeyHint="search"
            onChange={(event) => setValue(event.target.value)}
            className="min-h-11 w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] py-0 pr-11 pl-4 text-[0.9375rem] text-[var(--ink-primary)] transition-colors outline-none placeholder:text-[var(--ink-secondary)] focus:border-[var(--accent-primary)]"
          />
          <button
            type="submit"
            aria-label="Buscar"
            className="absolute top-0 right-0 inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl text-[var(--ink-secondary)] transition-colors hover:text-[var(--accent-primary)]"
          >
            <SearchIcon />
          </button>
        </form>

        <HeaderActions
          resolvedTheme={resolved}
          cartCount={cartCount}
          onToggleTheme={toggle}
          onOpenPreferences={onOpenPreferences}
          onOpenCart={onOpenCart}
        />
      </div>
    </header>
  );
}
