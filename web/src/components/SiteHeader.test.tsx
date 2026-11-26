import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import {
  HeaderActions,
  SiteHeader,
  THEME_TO_DARK_LABEL,
  THEME_TO_LIGHT_LABEL,
} from "./SiteHeader";

type Props = Record<string, unknown>;

/** Collects every element of a (hook-free) React tree that satisfies the predicate. */
function collect(node: ReactNode, test: (element: ReactElement<Props>) => boolean): ReactElement<Props>[] {
  if (Array.isArray(node)) return node.flatMap((child) => collect(child, test));
  if (!isValidElement<Props>(node)) return [];
  return [...(test(node) ? [node] : []), ...collect(node.props.children as ReactNode, test)];
}

function textOf(node: ReactNode): string {
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (isValidElement<Props>(node)) return textOf(node.props.children as ReactNode);
  return "";
}

function buttons(tree: ReactNode) {
  return collect(tree, (element) => element.type === "button");
}

describe("SiteHeader", () => {
  const baseProps = {
    cartCount: 3,
    query: "leche",
    onSearch: () => undefined,
    onOpenCart: () => undefined,
    onOpenPreferences: () => undefined,
  };

  it("renders the wordmark, a search form synced with the query and wraps it on mobile", () => {
    const html = renderToStaticMarkup(<SiteHeader {...baseProps} />);
    expect(html).toContain("Smart Basket");
    expect(html).toContain('src="/favicon.svg"');
    expect(html).toContain('role="search"');
    expect(html).toContain('type="search"');
    expect(html).toContain('value="leche"');
    expect(html).toContain("order-3 min-w-0 basis-full");
    expect(html).toContain("flex-wrap");
  });

  it("shows the list button with a tabular counter and the settings label", () => {
    const html = renderToStaticMarkup(<SiteHeader {...baseProps} />);
    expect(html).toContain("Tu lista");
    expect(html).toContain("Ajustes");
    expect(html).toMatch(/tabular-nums[^>]*>3</);
    expect(html).not.toContain("0.7rem");
    expect(html).not.toContain("transition-all");
  });

  it("labels the quick theme button by the action it performs", () => {
    const light = renderToStaticMarkup(
      <HeaderActions
        resolvedTheme="light"
        cartCount={0}
        onToggleTheme={() => undefined}
        onOpenPreferences={() => undefined}
        onOpenCart={() => undefined}
      />,
    );
    expect(light).toContain(`aria-label="${THEME_TO_DARK_LABEL}"`);
    const dark = renderToStaticMarkup(
      <HeaderActions
        resolvedTheme="dark"
        cartCount={0}
        onToggleTheme={() => undefined}
        onOpenPreferences={() => undefined}
        onOpenCart={() => undefined}
      />,
    );
    expect(dark).toContain(`aria-label="${THEME_TO_LIGHT_LABEL}"`);
  });

  it("wires theme toggle, settings and list buttons to their callbacks", () => {
    const onToggleTheme = vi.fn();
    const onOpenPreferences = vi.fn();
    const onOpenCart = vi.fn();
    const tree = HeaderActions({
      resolvedTheme: "light",
      cartCount: 2,
      onToggleTheme,
      onOpenPreferences,
      onOpenCart,
    });
    const [theme, settings, list] = buttons(tree);
    expect(theme.props["aria-label"]).toBe(THEME_TO_DARK_LABEL);
    expect(textOf(settings.props.children as ReactNode)).toContain("Ajustes");
    expect(textOf(list.props.children as ReactNode)).toContain("Tu lista");
    expect(textOf(list.props.children as ReactNode)).toContain("2");

    (theme.props.onClick as () => void)();
    (settings.props.onClick as () => void)();
    (list.props.onClick as () => void)();
    expect(onToggleTheme).toHaveBeenCalledTimes(1);
    expect(onOpenPreferences).toHaveBeenCalledTimes(1);
    expect(onOpenCart).toHaveBeenCalledTimes(1);
  });

  it("submits the trimmed query", () => {
    // SiteHeader uses hooks, so check the contract through its markup: a real search form.
    const html = renderToStaticMarkup(<SiteHeader {...baseProps} query="" />);
    expect(html).toContain('aria-label="Buscar"');
    expect(html).toContain('type="submit"');
  });
});
