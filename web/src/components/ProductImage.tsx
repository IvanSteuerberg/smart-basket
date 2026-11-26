import { useEffect, useState } from "react";

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
  /** Extra classes for the aspect box (rounding, margins). */
  className?: string;
}

/**
 * Square product photo with lazy loading and an inline fallback when it fails. Supermarket photos
 * are cut out on white, so the frame stays light in dark mode too (`--logo-plate`).
 */
export function ProductImage({ src, alt, className = "" }: ProductImageProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const box = `block aspect-square overflow-hidden ${className}`;

  // A new photo gets a fresh chance even if the previous one failed.
  useEffect(() => {
    setFailedSrc(null);
  }, [src]);

  if (src === null || failedSrc === src) {
    return (
      <span
        role="img"
        aria-label={alt}
        className={`${box} flex items-center justify-center bg-[var(--surface-elevated)] text-[var(--ink-secondary)]`}
      >
        <ShoppingBagIcon />
      </span>
    );
  }

  return (
    <span className={`${box} border border-[var(--border-subtle)] bg-[var(--logo-plate,#ffffff)]`}>
      <img
        src={src}
        alt={alt}
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        className="h-full w-full object-contain p-2"
        onError={() => setFailedSrc(src)}
      />
    </span>
  );
}
