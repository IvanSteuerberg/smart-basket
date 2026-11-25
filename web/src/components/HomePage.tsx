import { useState, type FormEvent } from "react";
import type { ActiveChain, CatalogSection } from "../api";
import { catalogHash, LIST_HASH } from "../router";
import {
  HOME_SEARCH_PLACEHOLDER,
  HOW_IT_WORKS,
  SEARCH_SUGGESTIONS,
} from "../texts";
import { CHAINS, ChainLogoPlate } from "./ChainLogo";
import { ProductImage } from "./ProductImage";

const NUMBER_FORMAT = new Intl.NumberFormat("es-ES", { useGrouping: "always" });

/** «1.240 productos»: es-ES grouping, also for four-digit numbers. */
export function productCountLabel(count: number): string {
  return `${NUMBER_FORMAT.format(count)} ${count === 1 ? "producto" : "productos"}`;
}

/** Always names what the number counts, so it is never an ambiguous bare figure. */
export function chainCountLabel(chain: ActiveChain): string {
  if (chain.store_count > 0) {
    return `${NUMBER_FORMAT.format(chain.store_count)} ${chain.store_count === 1 ? "tienda" : "tiendas"}`;
  }
  return productCountLabel(chain.product_count);
}

const SKELETON = "animate-pulse rounded-xl bg-[var(--surface-elevated)] motion-reduce:animate-none";

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)]";

export interface HomePageProps {
  sections: CatalogSection[];
  sectionsError: string | null;
  sectionsLoading: boolean;
  chains: ActiveChain[];
  chainsLoading: boolean;
  onSearch: (query: string) => void;
  onWriteList: () => void;
}

export function HomePage({
  sections,
  sectionsError,
  sectionsLoading,
  chains,
  chainsLoading,
  onSearch,
  onWriteList,
}: HomePageProps) {
  const [query, setQuery] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSearch(query.trim());
  }

  const chainLink =
    "flex min-h-14 items-center gap-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] p-2 pr-3 transition-colors hover:border-[var(--accent-primary)] " +
    FOCUS;

  return (
    <main className="mx-auto min-w-0 max-w-6xl px-4 pt-8 pb-16 text-[0.9375rem] text-[var(--ink-primary)] min-[540px]:px-5">
      <section className="grid gap-4 pb-8">
        <h1 className="text-[1.75rem] font-extrabold tracking-tight text-[var(--ink-primary)] sm:text-[2.125rem]">
          Tu compra más barata en León
        </h1>
        <p className="text-[0.9375rem] text-[var(--ink-secondary)]">
          Elige lo que necesitas y te decimos en qué supermercado comprarlo.
        </p>

        <form role="search" onSubmit={submit} className="flex max-w-2xl flex-col gap-2 sm:flex-row">
          <input
            type="search"
            value={query}
            placeholder={HOME_SEARCH_PLACEHOLDER}
            aria-label={HOME_SEARCH_PLACEHOLDER}
            autoComplete="off"
            enterKeyHint="search"
            onChange={(event) => setQuery(event.target.value)}
            className="min-h-12 w-full min-w-0 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-4 text-[0.9375rem] text-[var(--ink-primary)] transition-colors outline-none placeholder:text-[var(--ink-secondary)] focus:border-[var(--accent-primary)] sm:flex-1"
          />
          <button
            type="submit"
            className={`min-h-12 rounded-xl bg-[var(--accent-primary)] px-6 text-[0.9375rem] font-bold text-[var(--accent-on-primary)] transition-colors hover:bg-[var(--accent-primary-hover)] ${FOCUS}`}
          >
            Buscar
          </button>
        </form>

        <div className="flex flex-wrap items-center gap-2">
          {SEARCH_SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => onSearch(suggestion)}
              className={`min-h-11 rounded-full border border-[var(--border-subtle)] bg-[var(--surface-card)] px-3 text-[0.8125rem] font-medium text-[var(--ink-primary)] transition-colors hover:border-[var(--accent-primary)] hover:text-[var(--accent-primary)] ${FOCUS}`}
            >
              {suggestion}
            </button>
          ))}
        </div>

        <div>
          <a
            href={LIST_HASH}
            onClick={onWriteList}
            className={`inline-flex min-h-11 items-center rounded-xl border border-[var(--border-subtle)] px-4 text-[0.9375rem] font-semibold text-[var(--accent-primary)] transition-colors hover:border-[var(--accent-primary)] ${FOCUS}`}
          >
            Escribir mi lista
          </a>
        </div>
      </section>

      <section className="border-t border-[var(--border-subtle)] py-8" aria-labelledby="home-sections">
        <h2 id="home-sections" className="text-[1.375rem] font-bold tracking-tight">
          Compra por secciones
        </h2>
        {sectionsError && (
          <p role="alert" className="mt-2 text-[0.9375rem] font-semibold text-[var(--danger-fg)]">
            {sectionsError}
          </p>
        )}
        {sectionsLoading ? (
          <div
            data-testid="sections-skeleton"
            aria-busy="true"
            aria-label="Cargando secciones"
            className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
          >
            {Array.from({ length: 8 }, (_, index) => (
              <div key={index} className={`${SKELETON} h-48`} />
            ))}
          </div>
        ) : (
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {sections.map((section) => (
              <a
                key={section.key}
                href={catalogHash(section.key)}
                className={`group flex min-w-0 flex-col overflow-hidden rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] transition-colors hover:border-[var(--accent-primary)] ${FOCUS}`}
              >
                <ProductImage
                  src={section.image_url}
                  alt={section.name}
                  className="bg-[var(--surface-elevated)]"
                />
                <span className="flex flex-col gap-0.5 p-3">
                  <span className="text-[0.9375rem] font-bold">{section.name}</span>
                  <span className="tabular-nums text-[0.8125rem] text-[var(--ink-secondary)]">
                    {productCountLabel(section.products)}
                  </span>
                </span>
              </a>
            ))}
          </div>
        )}
      </section>

      <section className="border-t border-[var(--border-subtle)] py-8" aria-labelledby="home-chains">
        <h2 id="home-chains" className="text-[1.375rem] font-bold tracking-tight">
          Supermercados en León
        </h2>
        {chainsLoading ? (
          <div
            data-testid="chains-skeleton"
            aria-busy="true"
            aria-label="Cargando supermercados"
            className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
          >
            {Array.from({ length: 4 }, (_, index) => (
              <div key={index} className={`${SKELETON} h-14`} />
            ))}
          </div>
        ) : chains.length > 0 ? (
          <ul className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {chains.map((chain) => (
              <li key={chain.code} className="min-w-0">
                <a
                  href={catalogHash(null, "super", { chains: [chain.code] })}
                  className={chainLink}
                >
                  <ChainLogoPlate chain={chain.name} />
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate text-[0.9375rem] font-bold">{chain.name}</span>
                    <span className="tabular-nums text-[0.8125rem] text-[var(--ink-secondary)]">
                      {chainCountLabel(chain)}
                    </span>
                  </span>
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <ul className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {CHAINS.map((chain) => (
              <li key={chain.code} className="min-w-0">
                <a
                  href={catalogHash(null, "super", { chains: [chain.code] })}
                  className={chainLink}
                >
                  <ChainLogoPlate chain={chain.name} />
                  <span className="truncate text-[0.9375rem] font-bold">{chain.name}</span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="border-t border-[var(--border-subtle)] pt-8" aria-labelledby="home-how">
        <h2 id="home-how" className="text-[1.375rem] font-bold tracking-tight">
          Cómo funciona
        </h2>
        <ol className="mt-4 grid gap-6 sm:grid-cols-3">
          {HOW_IT_WORKS.map((step, index) => (
            <li key={step.title} className="flex gap-3">
              <span
                aria-hidden="true"
                className="tabular-nums flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--accent-soft)] text-[0.9375rem] font-bold text-[var(--accent-primary)]"
              >
                {index + 1}
              </span>
              <div className="min-w-0">
                <p className="text-[0.9375rem] font-bold">{step.title}</p>
                <p className="mt-1 text-[0.9375rem] text-[var(--ink-secondary)]">{step.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}
