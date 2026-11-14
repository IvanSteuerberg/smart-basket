// User-visible texts shared by more than one step.

import type { ProductSort } from "./api";

export const PRODUCT_SEARCH_PLACEHOLDER = "Busca un producto: yogur, aceite, detergente…";
export const HOME_SEARCH_PLACEHOLDER = "Busca un producto: leche, huevos, aceite…";

export const SEARCH_SUGGESTIONS = ["Leche", "Huevos", "Aceite de oliva", "Plátanos", "Café"];

export const CART_EMPTY = "Tu cesta está vacía.";

export const CART_UNCALCULABLE =
  "Este producto aún no está clasificado; no podemos calcular su cesta todavía.";

export const ADD_SPECIFIC = "Añadir este producto";
export const ADD_GENERIC_PREFIX = "Añadir cualquier";

export const CART_SAVE = "Guardar lista";
export const CART_CALCULATE = "Calcular cesta";
export const CART_TITLE = "Tu cesta";

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
