import { useState } from "react";

/** Brand colours, also used by the fallback badge when the logo file is missing. */
export const CHAIN_COLORS: Record<string, string> = {
  mercadona: "#00843d",
  carrefour: "#004e9f",
  dia: "#e2001a",
  lidl: "#0050aa",
  alcampo: "#e30613",
  eleclerc: "#0066b3",
  lupa: "#d71920",
  alimerka: "#f39200",
  gadis: "#e30613",
  aldi: "#00005f",
  froiz: "#007a33",
  elcorteingles: "#007a33",
};

export const CHAINS: { code: string; name: string }[] = [
  { code: "mercadona", name: "Mercadona" },
  { code: "carrefour", name: "Carrefour" },
  { code: "dia", name: "Dia" },
  { code: "lidl", name: "Lidl" },
  { code: "alcampo", name: "Alcampo" },
  { code: "eleclerc", name: "E.Leclerc" },
  { code: "lupa", name: "Lupa" },
  { code: "alimerka", name: "Alimerka" },
  { code: "gadis", name: "Gadis" },
  { code: "aldi", name: "Aldi" },
  { code: "froiz", name: "Froiz" },
  { code: "elcorteingles", name: "El Corte Inglés" },
];

/** «E.Leclerc» or «DIA» become the file name used under `public/logos`. */
export function chainCode(chain: string): string {
  return chain
    .toLowerCase()
    .normalize("NFD")
    .replace(/[^a-z]/g, "");
}

export interface ChainLogoProps {
  chain: string;
  className?: string;
}

export function ChainLogo({ chain, className = "" }: ChainLogoProps) {
  const [failed, setFailed] = useState(false);
  const code = chainCode(chain);

  if (!failed) {
    return (
      <img
        src={`/logos/${code}.svg`}
        alt={chain}
        loading="lazy"
        decoding="async"
        className={`object-contain ${className}`}
        onError={() => setFailed(true)}
      />
    );
  }

  return <ChainFallbackBadge chain={chain} className={className} />;
}

/** Coloured name badge shown when the logo file fails to load. */
export function ChainFallbackBadge({ chain, className = "" }: ChainLogoProps) {
  const brandColor = CHAIN_COLORS[chainCode(chain)];
  return (
    <span
      className={`flex items-center justify-center rounded-xl px-2 text-center text-[0.8125rem] font-bold ${className}`}
      style={{
        backgroundColor: brandColor ?? "var(--accent-primary)",
        color: brandColor ? "#ffffff" : "var(--accent-on-primary)",
      }}
    >
      {chain}
    </span>
  );
}

export interface ChainLogoPlateProps {
  chain: string;
  className?: string;
}

/**
 * Logo on a light plate: several marks use dark ink, so the plate keeps them legible in dark
 * mode. `--logo-plate` is not a palette token yet; the fallback is plain white.
 */
export function ChainLogoPlate({ chain, className = "" }: ChainLogoPlateProps) {
  return (
    <span
      className={`flex h-10 w-20 shrink-0 items-center justify-center rounded-lg bg-[var(--logo-plate,#ffffff)] p-1.5 ${className}`}
    >
      <ChainLogo chain={chain} className="max-h-full max-w-full" />
    </span>
  );
}
