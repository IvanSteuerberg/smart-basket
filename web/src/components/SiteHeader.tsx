import { useEffect, useState, type FormEvent } from "react";
import { HOME_HASH } from "../router";
import { PRODUCT_SEARCH_PLACEHOLDER } from "../texts";

function CartIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="h-5 w-5"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
    >
      <path d="M3 4h2l2.2 10.2a1 1 0 0 0 1 .8h8.5a1 1 0 0 0 1-.8L20 7H6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="9" cy="19" r="1.4" />
      <circle cx="17" cy="19" r="1.4" />
    </svg>
  );
}

export interface SiteHeaderProps {
  cartCount: number;
  /** Query shown in the search field, so suggestions and the page stay in sync. */
  query: string;
  onSearch: (query: string) => void;
  onOpenCart: () => void;
}

/** Logo, catalog search and the cart button, shared by every page. */
export function SiteHeader({ cartCount, query, onSearch, onOpenCart }: SiteHeaderProps) {
  const [value, setValue] = useState(query);

  useEffect(() => {
    setValue(query);
  }, [query]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSearch(value.trim());
  }

  return (
    <header className="sticky top-0 z-40 border-b border-stone-200 bg-white/95 text-slate-900 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-2 px-3 py-2.5 sm:gap-4 sm:px-4">
        <a href={HOME_HASH} className="flex shrink-0 items-center gap-2 text-brand">
          <img src="/favicon.svg" alt="" width={32} height={32} />
          <span className="text-base font-extrabold tracking-tight sm:text-lg">Smart Basket</span>
        </a>

        <form role="search" onSubmit={submit} className="min-w-0 flex-1">
          <input
            type="search"
            value={value}
            placeholder={PRODUCT_SEARCH_PLACEHOLDER}
            aria-label="Buscar en el catálogo"
            autoComplete="off"
            onChange={(event) => setValue(event.target.value)}
            className="w-full rounded-full border border-stone-300 bg-stone-50 px-4 py-2 text-sm text-slate-900 outline-none focus:border-brand focus:bg-white"
          />
        </form>

        <button
          type="button"
          onClick={onOpenCart}
          aria-label="Cesta"
          className="relative flex shrink-0 items-center gap-1.5 rounded-full bg-brand px-3 py-2 text-sm font-semibold text-white hover:bg-brand-dark"
        >
          <CartIcon />
          <span className="hidden sm:inline">Cesta</span>
          {cartCount > 0 && (
            <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-price px-1 text-[0.7rem] font-bold text-white">
              {cartCount}
            </span>
          )}
        </button>
      </div>
    </header>
  );
}
