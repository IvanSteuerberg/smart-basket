import { useState } from "react";
import type { CanonicalCard as CanonicalCardData } from "../api";
import { formatUnitPrice } from "../format";
import { canonicalHash } from "../router";
import { ADD_BUTTON_CLASS, QuantityStepper } from "./ProductCard";
import { ProductImage } from "./ProductImage";

export interface CanonicalCardProps {
  card: CanonicalCardData;
  onAdd: (card: CanonicalCardData) => void;
  /** Units of this generic product already in «Tu lista»; above 0 a stepper replaces «Añadir». */
  quantityInList?: number;
  onQuantityChange?: (card: CanonicalCardData, quantity: number) => void;
}

/** «3 productos en 2 tiendas», «1 producto». */
export function canonicalCountLabel(card: CanonicalCardData): string {
  const products = `${card.product_count} ${card.product_count === 1 ? "producto" : "productos"}`;
  const stores = card.chains.length;
  if (stores === 0) return products;
  return `${products} en ${stores} ${stores === 1 ? "tienda" : "tiendas"}`;
}

/** A generic product: no brand or size, with the cheapest price per unit. */
export function CanonicalCard({
  card,
  onAdd,
  quantityInList = 0,
  onQuantityChange,
}: CanonicalCardProps) {
  const [announcement, setAnnouncement] = useState("");
  const inList = !card.exact_only && quantityInList > 0 && onQuantityChange !== undefined;

  function handleAdd() {
    onAdd(card);
    setAnnouncement(`Añadido a tu lista: ${card.name}`);
  }

  function handleChange(quantity: number) {
    onQuantityChange?.(card, quantity);
    setAnnouncement(
      quantity < 1 ? `Quitado de tu lista: ${card.name}` : `${card.name}: ${quantity} en tu lista`,
    );
  }

  return (
    <article className="flex min-w-0 flex-col overflow-hidden rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface-card)] text-[var(--ink-primary)] transition-shadow hover:shadow-md">
      <a href={canonicalHash(card.id)} aria-label={card.name}>
        <ProductImage src={card.image_url} alt={card.name} className="rounded-none border-0" />
      </a>
      <div className="flex min-w-0 flex-1 flex-col gap-1 p-3">
        <a
          href={canonicalHash(card.id)}
          className="line-clamp-2 text-[0.9375rem] font-semibold leading-snug hover:text-[var(--accent-primary)]"
        >
          {card.name}
        </a>
        <p className="mt-auto pt-2 text-[0.9375rem] font-bold tabular-nums text-[var(--ink-primary)]">
          desde {formatUnitPrice(card.from_unit_price, card.base_unit)}
        </p>
        <p className="text-[0.8125rem] tabular-nums text-[var(--ink-secondary)]">
          {canonicalCountLabel(card)}
        </p>
        <div className="mt-2">
          {card.exact_only ? (
            <a href={canonicalHash(card.id)} className={ADD_BUTTON_CLASS}>
              Ver opciones
            </a>
          ) : inList ? (
            <QuantityStepper quantity={quantityInList} name={card.name} onChange={handleChange} />
          ) : (
            <button type="button" onClick={handleAdd} className={ADD_BUTTON_CLASS}>
              Añadir
            </button>
          )}
        </div>
        <p role="status" aria-live="polite" className="sr-only">
          {announcement}
        </p>
      </div>
    </article>
  );
}
