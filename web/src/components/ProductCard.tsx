import { useState } from "react";
import type { Product } from "../api";
import { formatEuro, formatUnitPrice } from "../format";
import type { UnifiedLine } from "../listStore";
import { productHash } from "../router";
import { ChainLogoPlate } from "./ChainLogo";
import { ProductImage } from "./ProductImage";

const BUTTON_FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)]";

export const ADD_BUTTON_CLASS = `inline-flex min-h-11 w-full items-center justify-center rounded-xl bg-[var(--accent-primary)] px-3 text-[0.9375rem] font-bold text-[var(--accent-on-primary)] transition-colors hover:bg-[var(--accent-primary-hover)] ${BUTTON_FOCUS}`;

/** Units in a whole-number line: only «ud» lines get the inline stepper. */
function wholeQuantity(line: UnifiedLine): number {
  const parsed = Math.round(Number(line.quantity.trim().replace(",", ".")));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

/** The line of «Tu lista» for a concrete product, or null. */
export function findProductLine(lines: UnifiedLine[], productId: number): UnifiedLine | null {
  return lines.find((line) => line.productId === productId && line.unit === "ud") ?? null;
}

/** The generic line of «Tu lista» for a generic product (same category), or null. */
export function findCanonicalLine(lines: UnifiedLine[], categoryKey: string): UnifiedLine | null {
  return (
    lines.find(
      (line) => line.productId === null && line.categoryKey === categoryKey && line.unit === "ud",
    ) ?? null
  );
}

export function lineQuantity(line: UnifiedLine | null): number {
  return line === null ? 0 : wholeQuantity(line);
}

/** `− N +` of a line: going under 1 removes it. Pure: the parent decides what to do. */
export function changeLineQuantity(
  line: UnifiedLine,
  next: number,
  onUpdateLineQuantity: (id: string, quantity: string) => void,
  onRemoveLine: (id: string) => void,
): void {
  if (next < 1) onRemoveLine(line.id);
  else onUpdateLineQuantity(line.id, String(next));
}

export interface QuantityStepperProps {
  quantity: number;
  /** Name of the product, for the accessible labels. */
  name: string;
  onChange: (quantity: number) => void;
}

/** Inline `− N +` control, 44px touch targets and a live number. */
export function QuantityStepper({ quantity, name, onChange }: QuantityStepperProps) {
  const button = `inline-flex min-h-11 min-w-11 items-center justify-center text-[1.375rem] font-bold text-[var(--accent-primary)] hover:bg-[var(--accent-soft)] ${BUTTON_FOCUS}`;
  return (
    <div
      role="group"
      aria-label={`Cantidad de ${name}`}
      className="flex min-h-11 w-full items-stretch justify-between overflow-hidden rounded-xl border border-[var(--accent-primary)] bg-[var(--surface-card)]"
    >
      <button
        type="button"
        aria-label={quantity <= 1 ? `Quitar ${name} de tu lista` : `Una unidad menos de ${name}`}
        onClick={() => onChange(quantity - 1)}
        className={button}
      >
        −
      </button>
      <span className="flex min-w-0 flex-1 items-center justify-center text-[0.9375rem] font-bold tabular-nums text-[var(--ink-primary)]">
        {quantity}
      </span>
      <button
        type="button"
        aria-label={`Una unidad más de ${name}`}
        onClick={() => onChange(quantity + 1)}
        className={button}
      >
        +
      </button>
    </div>
  );
}

export interface ProductCardProps {
  product: Product;
  onAdd: (product: Product) => void;
  /** Units already in «Tu lista»; above 0 the add button becomes a stepper. */
  quantityInList?: number;
  onQuantityChange?: (product: Product, quantity: number) => void;
}

export function ProductCard({
  product,
  onAdd,
  quantityInList = 0,
  onQuantityChange,
}: ProductCardProps) {
  const [announcement, setAnnouncement] = useState("");
  const inList = quantityInList > 0 && onQuantityChange !== undefined;

  function handleAdd() {
    onAdd(product);
    setAnnouncement(`Añadido a tu lista: ${product.name}`);
  }

  function handleChange(quantity: number) {
    onQuantityChange?.(product, quantity);
    setAnnouncement(
      quantity < 1
        ? `Quitado de tu lista: ${product.name}`
        : `${product.name}: ${quantity} en tu lista`,
    );
  }

  return (
    <article className="flex min-w-0 flex-col overflow-hidden rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface-card)] text-[var(--ink-primary)] transition-shadow hover:shadow-md">
      <a href={productHash(product.id)} aria-label={product.name}>
        <ProductImage src={product.image_url} alt={product.name} className="rounded-none border-0" />
      </a>
      <div className="flex min-w-0 flex-1 flex-col gap-1 p-3">
        <div className="flex min-w-0 items-center gap-2">
          <ChainLogoPlate chain={product.chain} className="h-7! w-14! p-1!" />
          {product.brand && (
            <p className="min-w-0 truncate text-[0.8125rem] font-semibold text-[var(--ink-secondary)]">
              {product.brand}
            </p>
          )}
        </div>
        <a
          href={productHash(product.id)}
          className="line-clamp-2 text-[0.9375rem] font-semibold leading-snug hover:text-[var(--accent-primary)]"
        >
          {product.name}
        </a>
        {product.packaging && (
          <p className="text-[0.8125rem] text-[var(--ink-secondary)]">{product.packaging}</p>
        )}
        <div className="mt-auto flex flex-wrap items-baseline gap-x-2 pt-2">
          <p className="text-[1.375rem] font-bold tabular-nums text-[var(--ink-primary)]">
            {formatEuro(product.price)}
          </p>
          {product.on_promo === true && (
            <span className="rounded-md bg-[var(--savings-bg)] px-2 py-0.5 text-[0.8125rem] font-semibold text-[var(--savings-fg)]">
              Oferta
            </span>
          )}
        </div>
        <p className="text-[0.8125rem] tabular-nums text-[var(--ink-secondary)]">
          {formatUnitPrice(product.unit_price, product.base_unit)}
        </p>
        <div className="mt-2">
          {inList ? (
            <QuantityStepper
              quantity={quantityInList}
              name={product.name}
              onChange={handleChange}
            />
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
