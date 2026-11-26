// User-visible texts shared by more than one step.

import type { CanonicalSort, ProductSort, Unit } from "./api";

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
  { value: "popular", label: "Más populares" },
  { value: "unit_price", label: "Más barato por unidad" },
  { value: "price", label: "Menor precio" },
  { value: "name", label: "Nombre (A a Z)" },
];

// Catalog filters
export const CATALOG_DIETARY_NOTICE =
  "Comprueba siempre la etiqueta del fabricante. El filtro se basa en el nombre publicado por el supermercado.";
export const CATALOG_SECTION_MISSING = "Esta sección no existe.";
export const CATALOG_SEE_ALL = "Ver todo el catálogo";
export const CATALOG_NEAR_NEEDS_ORIGIN = "Para ver lo que hay cerca, elige antes una dirección en";

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

// Unified list ("Tu lista"): one list for the catalog, the quick drawer and the list screen.
export const LIST_EMPTY = "Tu lista está vacía. Añade productos del catálogo o escríbela abajo.";
export const LIST_EDIT = "Editar lista";
export const LIST_FULL = "Ver lista completa";
export const LIST_SAVED_LISTS = "Listas guardadas";
export const LIST_ADD_FROM_CATALOG = "Añadir desde el catálogo";
export const LIST_ADD_TEXT = "Añadir a la lista";
export const LIST_TEXT_LABEL = "Escribe tu lista";
export const LIST_TEXT_PLACEHOLDER = "Una cosa por línea: 2 l de leche, pan de molde, pollo…";
export const LIST_REMOVE = "Quitar";
export const LIST_ORIGIN_REQUIRED = "Indica desde dónde sales para calcular tu plan.";
export const LIST_DEGRADED =
  "Hemos interpretado la lista sin el modelo de lenguaje: revisa las líneas marcadas.";
export const LIST_UNCLASSIFIED_LINE = "Falta elegir el producto antes de calcular.";

export const BRAND_ANY = "Cualquier marca";
export const BRAND_ONLY_PRODUCT = "Solo este producto";
export const BRAND_ONLY_BRAND = "Solo esta marca";
export const BRAND_EXACT_ONLY = "Solo este producto concreto";
export const BRAND_SWITCH = "Me da igual la marca";
export const BRAND_SWITCH_HELP = "Compara con cualquier marca en todas las líneas.";

export const SAVED_LISTS_TITLE = "Listas guardadas";
export const SAVED_LISTS_SAVE_TITLE = "Guardar la lista actual";
export const SAVED_LISTS_MINE_TITLE = "Mis listas guardadas";
export const SAVED_LISTS_NAME_LABEL = "Nombre de la lista";
export const SAVED_LISTS_NAME_REQUIRED = "Escribe un nombre para la lista.";
export const SAVED_LISTS_NAME_REPLACES = "Ya existe una lista con ese nombre: se sustituirá.";
export const SAVED_LISTS_NAME_TAKEN = "Ya tienes otra lista con ese nombre.";
export const SAVED_LISTS_EMPTY = "Todavía no has guardado ninguna lista.";
export const SAVED_LISTS_NOTHING_TO_SAVE = "Añade productos a tu lista para poder guardarla.";

/** Spanish plural: «1 envase», «2 envases». */
function plural(count: number, one: string, many: string): string {
  return count === 1 ? one : many;
}

/** A decimal string with a dot, shown with a comma as in Spain. */
function displayNumber(quantity: string): string {
  return quantity.trim().replace(".", ",");
}

/**
 * Quantity with its unit spelled out (B12): «1 unidad», «2 unidades», «1 envase» for a concrete
 * product, and «2 l», «500 g», «1,5 kg» for weight or volume.
 */
export function quantityLabel(quantity: string, unit: Unit, concrete: boolean): string {
  const shown = displayNumber(quantity);
  if (unit !== "ud") return `${shown} ${unit}`;
  const count = Number(quantity.trim().replace(",", "."));
  const [one, many] = concrete ? ["envase", "envases"] : ["unidad", "unidades"];
  return `${shown} ${plural(count, one, many)}`;
}

/** «Cualquier marca de leche entera»: «marca» is the head noun, so no gender agreement is needed. */
export function anyBrandOf(categoryName: string): string {
  const name = categoryName.trim().toLocaleLowerCase("es");
  return name === "" ? BRAND_ANY : `${BRAND_ANY} de ${name}`;
}

/** Text of the single brand control of a concrete line. */
export function pinBrandLabel(pinned: boolean, brand: string): string {
  if (!pinned) return BRAND_ANY;
  return brand.trim() === "" ? BRAND_ONLY_PRODUCT : BRAND_ONLY_BRAND;
}

/** «Resuelve la línea marcada…» / «Resuelve las 3 líneas marcadas…» */
export function unresolvedAlert(count: number): string {
  const lines = count === 1 ? "la línea marcada" : `las ${count} líneas marcadas`;
  return `Resuelve ${lines} antes de calcular tu plan.`;
}

/** «Hasta 1 tienda», «Hasta 2 tiendas». */
export function maxStoresLabel(count: number): string {
  return `Hasta ${count} ${plural(count, "tienda", "tiendas")}`;
}
