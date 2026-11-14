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

  return (
    <span
      className={`flex items-center justify-center rounded-xl px-2 text-center text-xs font-bold text-white ${className}`}
      style={{ backgroundColor: CHAIN_COLORS[code] ?? "#2f6f4e" }}
    >
      {chain}
    </span>
  );
}
