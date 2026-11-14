// Spanish formatting of the values the API returns.

import type { Decimal } from "./api";

export function parseDecimal(value: Decimal): number {
  if (typeof value === "number") return value;
  const normalized = value.trim().replace(",", ".");
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

function formatNumber(value: Decimal, digits: number): string {
  const parsed = parseDecimal(value);
  if (!Number.isFinite(parsed)) return String(value);
  return new Intl.NumberFormat("es-ES", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(parsed);
}

/** Amount with two decimals and the euro sign, for prices and totals. */
export function formatEuro(value: Decimal): string {
  return `${formatNumber(value, 2)} €`;
}

/** Amount without unit, for sentences that already carry one. */
export function formatAmount(value: Decimal): string {
  return formatNumber(value, 2);
}

/** Quantities such as packs or bought amounts, without trailing zeros. */
export function formatQuantity(value: Decimal): string {
  return new Intl.NumberFormat("es-ES", { maximumFractionDigits: 3 }).format(parseDecimal(value) || 0);
}

/** A travel time in whole minutes; the raw value if it is not a number. */
export function formatMinutes(value: Decimal): string {
  const parsed = parseDecimal(value);
  if (!Number.isFinite(parsed)) return String(value);
  return new Intl.NumberFormat("es-ES", { maximumFractionDigits: 0 }).format(Math.round(parsed));
}

/** A full timestamp as `dd/mm/yyyy HH:mm`; the raw value if it is not a date. */
export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (part: number) => String(part).padStart(2, "0");
  return (
    `${pad(date.getDate())}/${pad(date.getMonth() + 1)}/${date.getFullYear()} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}
