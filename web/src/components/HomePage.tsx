import { useState, type FormEvent } from "react";
import type { CatalogSection } from "../api";
import { catalogHash, LIST_HASH } from "../router";
import {
  HOME_SEARCH_PLACEHOLDER,
  HOW_IT_WORKS,
  SEARCH_SUGGESTIONS,
} from "../texts";
import { CHAINS, ChainLogo } from "./ChainLogo";
import { ProductImage } from "./ProductImage";

export interface HomePageProps {
  sections: CatalogSection[];
  sectionsError: string | null;
  onSearch: (query: string) => void;
  onWriteList: () => void;
}

export function HomePage({ sections, sectionsError, onSearch, onWriteList }: HomePageProps) {
  const [query, setQuery] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSearch(query.trim());
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <section className="rounded-3xl bg-gradient-to-br from-brand to-brand-dark px-5 py-10 text-center text-white shadow-lg">
        <h1 className="text-2xl font-extrabold sm:text-4xl">Tu compra más barata en León</h1>
        <p className="mx-auto mt-2 max-w-xl text-sm text-white/85 sm:text-base">
          Elige lo que necesitas y te decimos en qué supermercado comprarlo.
        </p>

        <form
          role="search"
          onSubmit={submit}
          className="mx-auto mt-6 flex max-w-2xl flex-col gap-2 sm:flex-row"
        >
          <input
            type="search"
            value={query}
            placeholder={HOME_SEARCH_PLACEHOLDER}
            aria-label={HOME_SEARCH_PLACEHOLDER}
            autoComplete="off"
            onChange={(event) => setQuery(event.target.value)}
            className="w-full rounded-full border-0 bg-white px-5 py-3 text-slate-900 shadow-md outline-none"
          />
          <button
            type="submit"
            className="rounded-full bg-price px-6 py-3 font-semibold text-white hover:bg-price/90"
          >
            Buscar
          </button>
        </form>

        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {SEARCH_SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => onSearch(suggestion)}
              className="rounded-full border border-white/25 bg-white/10 px-3 py-1.5 text-sm text-white hover:bg-white/20"
            >
              {suggestion}
            </button>
          ))}
        </div>

        <a
          href={LIST_HASH}
          onClick={onWriteList}
          className="mt-5 inline-block text-sm font-semibold text-white underline underline-offset-4 hover:text-white/80"
        >
          Escribir la lista a mano
        </a>
      </section>

      <section className="mt-10">
        <h2 className="text-xl font-extrabold text-slate-900">Compra por secciones</h2>
        {sectionsError && (
          <p role="alert" className="mt-2 text-sm font-semibold text-red-700">
            {sectionsError}
          </p>
        )}
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {sections.map((section) => (
            <a
              key={section.key}
              href={catalogHash(section.key)}
              className="group overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm transition-shadow hover:shadow-md"
            >
              <ProductImage
                src={section.image_url}
                alt={section.name}
                className="bg-stone-100 transition-transform group-hover:scale-105"
              />
              <div className="p-3">
                <p className="font-semibold text-slate-900">{section.name}</p>
                <p className="text-xs text-stone-500">
                  {section.products} {section.products === 1 ? "producto" : "productos"}
                </p>
              </div>
            </a>
          ))}
        </div>
      </section>

      <section className="mt-10 rounded-3xl border border-stone-200 bg-white p-5">
        <h2 className="text-center text-xl font-extrabold text-slate-900">
          Compra en tus supermercados
        </h2>
        <ul className="mt-4 flex flex-wrap items-center justify-center gap-3">
          {CHAINS.map((chain) => (
            <li
              key={chain.code}
              className="flex h-14 w-28 items-center justify-center rounded-xl bg-stone-50 p-2"
            >
              <ChainLogo chain={chain.name} className="max-h-full max-w-full" />
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-10">
        <h2 className="text-xl font-extrabold text-slate-900">Cómo funciona</h2>
        <ol className="mt-4 grid gap-3 sm:grid-cols-3">
          {HOW_IT_WORKS.map((step, index) => (
            <li key={step.title} className="rounded-2xl border border-stone-200 bg-white p-5">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand text-sm font-bold text-white">
                {index + 1}
              </span>
              <p className="mt-3 font-semibold text-slate-900">{step.title}</p>
              <p className="mt-1 text-sm text-stone-600">{step.text}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
