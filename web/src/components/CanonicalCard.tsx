import type { CanonicalCard as CanonicalCardData } from "../api";
import { formatUnitPrice } from "../format";
import { canonicalHash } from "../router";
import { ProductImage } from "./ProductImage";

export interface CanonicalCardProps {
  card: CanonicalCardData;
  onAdd: (card: CanonicalCardData) => void;
}

/** A generic product: no brand or size, with the cheapest price per unit. */
export function CanonicalCard({ card, onAdd }: CanonicalCardProps) {
  return (
    <article className="flex flex-col overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm transition-shadow hover:shadow-md">
      <a href={canonicalHash(card.id)} aria-label={card.name}>
        <ProductImage src={card.image_url} alt={card.name} />
      </a>
      <div className="flex flex-1 flex-col gap-1 p-3 text-slate-900">
        <a
          href={canonicalHash(card.id)}
          className="line-clamp-2 text-sm font-semibold leading-snug hover:text-brand"
        >
          {card.name}
        </a>
        <p className="mt-auto pt-2 text-lg font-bold text-price">
          desde {formatUnitPrice(card.from_unit_price, card.base_unit)}
        </p>
        <p className="text-xs text-stone-500">
          {card.product_count} {card.product_count === 1 ? "producto" : "productos"}
        </p>
        <button
          type="button"
          onClick={() => onAdd(card)}
          className="mt-2 w-full rounded-full bg-brand px-3 py-2 text-sm font-semibold text-white hover:bg-brand-dark"
        >
          Añadir
        </button>
      </div>
    </article>
  );
}
