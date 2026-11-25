import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CanonicalPage, CanonicalProductList, PRODUCTS_PAGE_SIZE } from "./CanonicalPage";
import type { Product } from "../api";

function products(count: number): Product[] {
  return Array.from({ length: count }, (_, index) => ({
    id: index + 1,
    name: `Leche ${index + 1}`,
    brand: null,
    private_label: false,
    packaging: null,
    image_url: null,
    chain: "dia",
    price: "0.89",
    unit_price: "0.89",
    base_unit: "l" as const,
    base_quantity: "1",
    canonical: null,
  }));
}

function list(count: number, visible: number) {
  return renderToStaticMarkup(
    <CanonicalProductList
      products={products(count)}
      visible={visible}
      lines={[]}
      onAddSpecific={() => undefined}
      onUpdateLineQuantity={() => undefined}
      onRemoveLine={() => undefined}
      onShowMore={() => undefined}
    />,
  );
}

describe("CanonicalProductList (B9)", () => {
  it("shows the first 24 and how many are left", () => {
    const html = list(100, PRODUCTS_PAGE_SIZE);
    expect(html.match(/<article/g)).toHaveLength(24);
    expect(html).toContain("Ver más productos (quedan 76)");
  });

  it("reveals 24 more each time and hides the button at the end", () => {
    expect(list(100, 48).match(/<article/g)).toHaveLength(48);
    expect(list(100, 48)).toContain("quedan 52");
    const all = list(100, 120);
    expect(all.match(/<article/g)).toHaveLength(100);
    expect(all).not.toContain("Ver más productos");
  });

  it("shows no button when everything fits", () => {
    const html = list(24, PRODUCTS_PAGE_SIZE);
    expect(html.match(/<article/g)).toHaveLength(24);
    expect(html).not.toContain("Ver más productos");
  });

  it("renders nothing without products", () => {
    expect(list(0, PRODUCTS_PAGE_SIZE)).toBe("");
  });
});

describe("CanonicalPage", () => {
  it("goes back to the exact catalog URL it was given (A4)", () => {
    const back = "#/catalogo/lacteos?oferta=1&cadena=dia";
    const html = renderToStaticMarkup(
      <CanonicalPage
        id={5}
        backHref={back}
        lines={[]}
        onAddGeneric={() => undefined}
        onAddSpecific={() => undefined}
        onUpdateLineQuantity={() => undefined}
        onRemoveLine={() => undefined}
      />,
    );
    expect(html).toContain(`href="${back.replace("&", "&amp;")}"`);
    expect(html).toContain("Volver al catálogo");
  });
});
