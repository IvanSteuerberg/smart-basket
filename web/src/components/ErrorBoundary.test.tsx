import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

describe("ErrorBoundary", () => {
  it("renders its children when nothing fails", () => {
    const html = renderToStaticMarkup(
      <ErrorBoundary>
        <p>contenido</p>
      </ErrorBoundary>,
    );
    expect(html).toBe("<p>contenido</p>");
  });

  it("turns a render error into state and shows the Spanish recovery card", () => {
    const boundary = new ErrorBoundary({ children: <p>roto</p> });
    boundary.state = ErrorBoundary.getDerivedStateFromError(new Error("boom"));
    const html = renderToStaticMarkup(boundary.render());
    expect(html).toContain("Algo ha fallado al mostrar esta pantalla.");
    expect(html).toContain("Reintentar");
    expect(html).toContain("Ir al inicio");
    expect(html).toContain('href="#/"');
    expect(html).not.toContain("roto");
  });
});
