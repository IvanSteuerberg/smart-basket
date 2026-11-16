import { useState } from "react";

function ShoppingBagIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="h-10 w-10"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
    >
      <path d="M5 8h14l-1 12H6L5 8Z" strokeLinejoin="round" />
      <path d="M9 8V6a3 3 0 0 1 6 0v2" strokeLinecap="round" />
    </svg>
  );
}

export interface ProductImageProps {
  src: string | null;
  alt: string;
  /** Extra classes for the aspect box (rounding, background). */
  className?: string;
}

/** Square product photo with lazy loading and an inline fallback when it fails. */
export function ProductImage({ src, alt, className = "" }: ProductImageProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const box = `block aspect-square overflow-hidden ${className}`;

  if (src === null || failedSrc === src) {
    return (
      <span
        role="img"
        aria-label={alt}
        className={`${box} flex items-center justify-center bg-stone-100 text-stone-400`}
      >
        <ShoppingBagIcon />
      </span>
    );
  }

  return (
    <span className={`${box} bg-white`}>
      <img
        src={src}
        alt={alt}
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        className="h-full w-full object-cover"
        onError={() => setFailedSrc(src)}
      />
    </span>
  );
}
