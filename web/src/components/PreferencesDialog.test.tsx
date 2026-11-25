import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import {
  IMPORT_ERROR,
  IMPORT_OK,
  isOutsideRect,
  PREFERENCES_DIETARY_NOTICE,
  PreferencesDialog,
  runImport,
} from "./PreferencesDialog";

function render(dietaryRules: string[] = []): string {
  return renderToStaticMarkup(
    <PreferencesDialog
      open={false}
      onClose={() => undefined}
      dietaryRules={dietaryRules}
      onToggleDietaryRule={() => undefined}
      onExportProfile={() => undefined}
      onImportProfile={() => undefined}
    />,
  );
}

describe("PreferencesDialog", () => {
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

  it("offers the three theme states as a radio group", () => {
    const html = render();
    expect(html).toContain('role="radiogroup"');
    for (const label of ["Sistema", "Claro", "Oscuro"]) {
      expect(html).toMatch(new RegExp(`role="radio"[^>]*>${label}<`));
    }
  });

  it("shows dietary toggles reflecting the profile, with the FR-42 notice", () => {
    const html = render(["sin_gluten"]);
    expect(html).toContain("Sin gluten");
    expect(html).toContain("Sin lactosa");
    expect(html.match(/type="checkbox"/g)).toHaveLength(2);
    expect(html.match(/checked=""/g)).toHaveLength(1);
    expect(html).toContain(PREFERENCES_DIETARY_NOTICE);
    expect(PREFERENCES_DIETARY_NOTICE).toBe(
      "Comprueba siempre la etiqueta del fabricante. El filtro se basa en el nombre publicado por el supermercado.",
    );
  });

  it("has export and import buttons for the browser data", () => {
    const html = render();
    expect(html).toContain("Tus datos en este navegador");
    expect(html).toContain("Exportar preferencias (JSON)");
    expect(html).toContain("Importar preferencias (JSON)");
  });

  it("avoids long dashes and transition-all", () => {
    const html = render();
    expect(html).not.toContain("—");
    expect(html).not.toContain(" – ");
    expect(html).not.toContain("transition-all");
  });
});

describe("backdrop click detection", () => {
  const rect = { left: 100, right: 500, top: 50, bottom: 450 };

  it("is outside only beyond the dialog box", () => {
    expect(isOutsideRect(rect, 10, 10)).toBe(true);
    expect(isOutsideRect(rect, 600, 200)).toBe(true);
    expect(isOutsideRect(rect, 200, 500)).toBe(true);
    expect(isOutsideRect(rect, 200, 200)).toBe(false);
    expect(isOutsideRect(rect, 100, 50)).toBe(false);
  });
});

describe("runImport", () => {
  it("reports success when the import resolves", async () => {
    const onImport = vi.fn().mockResolvedValue(undefined);
    expect(await runImport("{}", onImport)).toEqual({ kind: "ok", message: IMPORT_OK });
    expect(onImport).toHaveBeenCalledWith("{}");
  });

  it("reports an error when the import throws or rejects", async () => {
    expect(
      await runImport("x", () => {
        throw new Error("bad");
      }),
    ).toEqual({ kind: "error", message: IMPORT_ERROR });
    expect(await runImport("x", () => Promise.reject(new Error("bad")))).toEqual({
      kind: "error",
      message: IMPORT_ERROR,
    });
  });
});
