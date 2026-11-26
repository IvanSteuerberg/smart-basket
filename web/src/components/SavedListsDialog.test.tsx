import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { SavedList } from "../storage";
import {
  productCountLabel,
  SavedListsDialog,
  sameNameExists,
  type SavedListsDialogProps,
} from "./SavedListsDialog";

function list(id: string, name: string, count: number): SavedList {
  return {
    id,
    name,
    created_at: "2026-11-01T10:00:00.000Z",
    updated_at: "2026-11-01T10:00:00.000Z",
    text: "",
    items: Array.from({ length: count }, (_, index) => ({
      id: `${id}-${index}`,
      text: "Leche",
      categoryKey: "leche",
      categoryName: "Leche",
      quantity: "1",
      unit: "ud" as const,
      brand: "",
      privateLabelOk: true,
      productId: null,
      accept: "equivalent" as const,
      locked: false,
      imageUrl: null,
      options: [],
      exactOnly: false,
    })),
  };
}

function render(overrides: Partial<SavedListsDialogProps> = {}): string {
  return renderToStaticMarkup(
    <SavedListsDialog
      open={false}
      onClose={() => undefined}
      lists={[list("a", "Semanal", 3), list("b", "Barbacoa", 1)]}
      currentCount={2}
      onSave={() => undefined}
      onLoad={() => undefined}
      onRename={() => undefined}
      onDelete={() => undefined}
      {...overrides}
    />,
  );
}

describe("SavedListsDialog", () => {
  it("is a native dialog labelled by its heading, without redundant ARIA", () => {
    const html = render();
    expect(html).toMatch(/^<dialog /);
    const labelledBy = /aria-labelledby="([^"]+)"/.exec(html)?.[1];
    expect(labelledBy).toBeTruthy();
    expect(html).toContain(`<h2 id="${labelledBy}"`);
    expect(html).not.toContain('role="dialog"');
    expect(html).not.toContain("aria-modal");
    expect(html).not.toMatch(/<dialog[^>]*class="[^"]*\b(flex|block|grid)\b/);
  });

  it("has a labelled name field and a save button, never window.prompt", () => {
    const html = render();
    expect(html).toContain("Guardar la lista actual");
    expect(html).toMatch(/<label[^>]*>Nombre de la lista<\/label>/);
    expect(html).toMatch(/<input[^>]*type="text"/);
    expect(html).toContain(">Guardar<");
  });

  it("lists the saved lists with a tabular product count and the three actions", () => {
    const html = render();
    expect(html).toContain("Mis listas guardadas");
    expect(html).toContain("Semanal");
    expect(html).toMatch(/tabular-nums[^>]*>3 productos</);
    expect(html).toMatch(/tabular-nums[^>]*>1 producto</);
    expect(html.match(/>Cargar</g)).toHaveLength(2);
    expect(html.match(/>Renombrar</g)).toHaveLength(2);
    expect(html.match(/>Borrar</g)).toHaveLength(2);
  });

  it("keeps every control at least 44px tall", () => {
    const html = render();
    const buttons = html.match(/<button[^>]*>/g) ?? [];
    expect(buttons.length).toBeGreaterThan(0);
    for (const button of buttons) expect(button).toContain("min-h-11");
  });

  it("explains an empty collection and an empty current list", () => {
    const html = render({ lists: [], currentCount: 0 });
    expect(html).toContain("Todavía no has guardado ninguna lista.");
    expect(html).toContain("Añade productos a tu lista para poder guardarla.");
    expect(html).not.toMatch(/<form/);
  });

  it("never asks with the browser's own dialogs", () => {
    expect(render()).not.toMatch(/prompt|confirm\(/);
  });
});

describe("sameNameExists", () => {
  const lists = [list("a", "Semanal", 1), list("b", "Barbacoa", 1)];

  it("ignores case and surrounding spaces", () => {
    expect(sameNameExists("  semanal ", lists, null)).toBe(true);
  });

  it("does not count the list being renamed", () => {
    expect(sameNameExists("Semanal", lists, "a")).toBe(false);
    expect(sameNameExists("Semanal", lists, "b")).toBe(true);
  });

  it("treats a blank name as free", () => {
    expect(sameNameExists("   ", lists, null)).toBe(false);
  });
});

describe("productCountLabel", () => {
  it("agrees in number", () => {
    expect(productCountLabel(1)).toBe("1 producto");
    expect(productCountLabel(0)).toBe("0 productos");
    expect(productCountLabel(12)).toBe("12 productos");
  });
});
