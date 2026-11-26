import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  CHAIN_COLORS,
  CHAINS,
  ChainFallbackBadge,
  ChainLogo,
  ChainLogoPlate,
  chainCode,
} from "./ChainLogo";

describe("ChainLogo", () => {
  it("lists the 12 chains, each with a brand colour", () => {
    expect(CHAINS).toHaveLength(12);
    const codes = CHAINS.map((chain) => chain.code);
    expect(codes).toContain("froiz");
    expect(codes).toContain("elcorteingles");
    for (const code of codes) expect(CHAIN_COLORS[code]).toBeTruthy();
  });

  it("derives the logo file name from the chain name", () => {
    expect(chainCode("El Corte Inglés")).toBe("elcorteingles");
    expect(chainCode("E.Leclerc")).toBe("eleclerc");
    expect(chainCode("DIA")).toBe("dia");
  });

  it("renders one image per chain pointing at its svg", () => {
    for (const chain of CHAINS) {
      const html = renderToStaticMarkup(<ChainLogo chain={chain.name} />);
      expect(html).toContain(`src="/logos/${chain.code}.svg"`);
      expect(html).toContain(`alt="${chain.name}"`);
    }
  });

  it("fallback badge uses the brand colour, or the accent token for an unknown chain", () => {
    const known = renderToStaticMarkup(<ChainFallbackBadge chain="Froiz" />);
    expect(known).toContain("background-color:#007a33");
    expect(known).toContain(">Froiz<");
    const unknown = renderToStaticMarkup(<ChainFallbackBadge chain="Desconocido" />);
    expect(unknown).toContain("var(--accent-primary)");
    expect(unknown).not.toContain("#2f6f4e");
  });

  it("puts the logo on a light plate so dark ink stays legible in dark mode", () => {
    const html = renderToStaticMarkup(<ChainLogoPlate chain="Lupa" />);
    expect(html).toContain("--logo-plate");
    expect(html).toContain("/logos/lupa.svg");
  });
});
