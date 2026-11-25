// User-visible texts shared by more than one step.

import type { CanonicalSort, ProductSort } from "./api";

// Error boundary
export const ERROR_BOUNDARY_TITLE = "Algo ha fallado al mostrar esta pantalla.";
export const ERROR_BOUNDARY_RETRY = "Reintentar";
export const ERROR_BOUNDARY_HOME = "Ir al inicio";

// Theme switcher
export const THEME_LABEL = "Tema";
export const THEME_SYSTEM = "Tema del sistema";
export const THEME_LIGHT = "Claro";
export const THEME_DARK = "Oscuro";

// Unified list
export const LIST_TITLE = "Tu lista";
export const PLAN_TITLE = "Tu plan de compra";
export const PLAN_CALCULATE = "Calcular plan";

// Catalog sort options for generic products
export const CANONICAL_SORT_OPTIONS: { value: CanonicalSort; label: string }[] = [
  { value: "relevance", label: "Relevancia" },
  { value: "popular", label: "Más opciones" },
  { value: "unit_price", label: "Precio por kg/l" },
  { value: "price", label: "Precio" },
  { value: "name", label: "Nombre" },
];

// Dietary filters (FR-42)
export const DIETARY_LABELS: Record<string, string> = {
  sin_gluten: "Sin gluten",
  sin_lactosa: "Sin lactosa",
  vegano: "Vegano",
  vegetariano: "Vegetariano",
  ecologico: "Ecológico",
};
export const DIETARY_DISCLAIMER =
  "Los filtros dietéticos se basan solo en lo que declara el supermercado en el nombre del producto. Comprueba siempre el etiquetado en tienda.";

export const PRODUCT_SEARCH_PLACEHOLDER = "Busca un producto: yogur, aceite, detergente…";
export const HOME_SEARCH_PLACEHOLDER = "Busca un producto: leche, huevos, aceite…";

export const SEARCH_SUGGESTIONS = ["Leche", "Huevos", "Aceite de oliva", "Plátanos", "Café"];

export const CART_EMPTY = "Tu cesta está vacía.";

export const CART_UNCALCULABLE =
  "Este producto aún no está clasificado; no podemos calcular su cesta todavía.";

export const ADD_SPECIFIC = "Añadir este producto";
export const ADD_GENERIC_PREFIX = "Añadir cualquier";

export const EXACT_ONLY_PICK = "Elegir en el catálogo";
export const EXACT_ONLY_SEE_PRODUCTS = "Ver productos";
export const exactOnlyLine = (text: string) =>
  `«${text}» depende del tono o del color: elige el producto concreto.`;

export const CATALOG_BY_PRODUCT = "Por producto";
export const CATALOG_BY_CHAIN = "Por supermercado";

export const CART_SAVE = "Guardar lista";
export const CART_CALCULATE = "Calcular cesta";
export const CART_TITLE = "Tu cesta";

export const CART_ACCEPT_EXACT = "Este producto";
export const CART_ACCEPT_ANY_PREFIX = "Cualquier";
export const CART_ACCEPT_LABEL = "Qué acepta esta línea";
export const CART_LOCK = "Fijar este producto";
export const CART_UNLOCK = "Quitar fijación";
export const CART_LOCK_HELP = "Fijado: no cambia aunque te dé igual la marca";

export const CART_ANY_BRAND = "Me da igual la marca";
export const CART_ANY_BRAND_HELP = "Compara con cualquier marca, salvo los productos fijados.";
export const CART_CHAINS = "Comprar solo en…";
export const CART_CHAINS_ALL = "Todas";

export const CART_EXPORT_PROFILE = "Exportar mis preferencias";
export const CART_IMPORT_PROFILE = "Importar preferencias";
export const CART_PROFILE_NOTICE =
  "Tus preferencias se guardan solo en este navegador; si borras sus datos, se pierden.";

export const SORT_OPTIONS: { value: ProductSort; label: string }[] = [
  { value: "unit_price", label: "Precio por kg/l" },
  { value: "price", label: "Precio" },
  { value: "name", label: "Nombre" },
];

export const HOW_IT_WORKS = [
  {
    title: "Haz tu lista",
    text: "Busca productos del catálogo o escríbela a mano.",
  },
  {
    title: "Elige desde dónde sales",
    text: "Tu casa, el trabajo o la dirección que prefieras.",
  },
  {
    title: "Te decimos dónde comprar cada cosa",
    text: "La cesta más barata y el recorrido más corto, tienda a tienda.",
  },
];
