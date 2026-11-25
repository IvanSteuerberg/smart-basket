import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ActiveChain, CatalogSection } from "../api";
import { catalogHash } from "../router";
import { SEARCH_SUGGESTIONS } from "../texts";
import { chainCountLabel, HomePage, productCountLabel, type HomePageProps } from "./HomePage";

const SECTIONS: CatalogSection[] = [
  { key: "lacteos", name: "Lácteos y huevos", products: 1240, image_url: null },
  { key: "carne", name: "Carne", products: 1, image_url: null },
];

const CHAINS: ActiveChain[] = [
  { code: "alimerka", name: "Alimerka", store_count: 7, product_count: 5000, last_price_at: null },
  { code: "froiz", name: "Froiz", store_count: 1, product_count: 300, last_price_at: null },
];

function render(overrides: Partial<HomePageProps> = {}): string {
  return renderToStaticMarkup(
    <HomePage
      sections={SECTIONS}
      sectionsError={null}
      sectionsLoading={false}
      chains={CHAINS}
      chainsLoading={false}
      onSearch={() => undefined}
      onWriteList={() => undefined}
      {...overrides}
    />,
  );
}

function attrHref(hash: string): string {
  return `href="${hash.replace(/&/g, "&amp;")}"`;
}

describe("HomePage", () => {
  it("opens with the search, not a marketing hero", () => {
    // Pass empty sections so `ProductImage` (updated in E7) does not leak legacy classes here.
    const html = render({ sections: [] });
    expect(html).toContain("Tu compra más barata en León");
    expect(html).toContain('type="search"');
    expect(html).toContain("Escribir mi lista");
    expect(html).toContain('href="#/lista"');
    expect(html).not.toContain("gradient");
    expect(html).not.toMatch(/bg-(white|stone|slate)/);
    expect(html).not.toContain("transition-all");
    expect(html).not.toContain("—");
    for (const suggestion of SEARCH_SUGGESTIONS) {
      expect(html).toContain(`>${suggestion}</button>`);
    }
  });

  it("shows 8 skeleton cards while sections load", () => {
    const html = render({ sectionsLoading: true, sections: [] });
    expect(html).toContain('data-testid="sections-skeleton"');
    expect(html.match(/animate-pulse/g)?.length).toBeGreaterThanOrEqual(8);
    expect(html).toContain("motion-reduce:animate-none");
    expect(html).not.toContain("Lácteos y huevos");
  });

  it("renders sections with a formatted, labelled count", () => {
    const html = render();
    expect(html).toContain("Lácteos y huevos");
    expect(html).toContain("1.240 productos");
    expect(html).toContain("1 producto<");
    expect(html).toContain('href="#/catalogo/lacteos"');
    expect(html).toContain("grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4");
  });

  it("lists only the active chains from the API as links with a clear store count", () => {
    const html = render();
    expect(html).toContain(attrHref(catalogHash(null, "super", { chains: ["alimerka"] })));
    expect(html).toContain(attrHref(catalogHash(null, "super", { chains: ["froiz"] })));
    expect(html).toContain("7 tiendas");
    expect(html).toContain("1 tienda<");
    expect(html).not.toContain("Mercadona");
    expect(html).not.toContain('data-testid="chains-skeleton"');
  });

  it("shows chain skeletons while loading and the static chains when the API gives none", () => {
    expect(render({ chainsLoading: true, chains: [] })).toContain('data-testid="chains-skeleton"');
    const fallback = render({ chains: [] });
    expect(fallback).toContain("Mercadona");
    expect(fallback).toContain("El Corte Inglés");
    expect(fallback).toContain(attrHref(catalogHash(null, "super", { chains: ["froiz"] })));
  });

  it("shows the sections error as an alert", () => {
    expect(render({ sectionsError: "Sin conexión" })).toContain('role="alert"');
  });

  it("labels counts so a bare number is never ambiguous", () => {
    expect(productCountLabel(25587)).toBe("25.587 productos");
    expect(chainCountLabel(CHAINS[0])).toBe("7 tiendas");
    expect(chainCountLabel({ ...CHAINS[0], store_count: 0, product_count: 12 })).toBe("12 productos");
  });
});
