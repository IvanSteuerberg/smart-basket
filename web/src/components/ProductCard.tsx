import type { Product } from "../api";
import { formatEuro, formatUnitPrice } from "../format";
import { productHash } from "../router";
import { ChainLogo } from "./ChainLogo";
import { ProductImage } from "./ProductImage";

export interface ProductCardProps {
  product: Product;
  onAdd: (product: Product) => void;
}

export function ProductCard({ product, onAdd }: ProductCardProps) {
  return (
    <article className="flex flex-col overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm transition-shadow hover:shadow-md">
      <a href={productHash(product.id)} aria-label={product.name}>
        <ProductImage src={product.image_url} alt={product.name} />
      </a>
      <div className="flex flex-1 flex-col gap-1 p-3 text-slate-900">
        <p className="text-[0.68rem] font-semibold uppercase tracking-wide text-stone-500">
          {product.brand ?? <ChainLogo chain={product.chain} className="h-4 w-auto" />}
        </p>
        <a
          href={productHash(product.id)}
          className="line-clamp-2 text-sm font-semibold leading-snug hover:text-brand"
        >
          {product.name}
        </a>
        {product.packaging && <p className="text-xs text-stone-500">{product.packaging}</p>}
        <p className="mt-auto pt-2 text-lg font-bold text-price">{formatEuro(product.price)}</p>
        <p className="text-xs text-stone-500">
          {formatUnitPrice(product.unit_price, product.base_unit)}
        </p>
        <button
          type="button"
          onClick={() => onAdd(product)}
          className="mt-2 w-full rounded-full bg-brand px-3 py-2 text-sm font-semibold text-white hover:bg-brand-dark"
        >
          Añadir
        </button>
      </div>
    </article>
  );
}
