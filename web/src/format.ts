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

/** Price per unit as the catalog shows it: «1,15 €/kg». */
export function formatUnitPrice(unitPrice: Decimal, baseUnit: string): string {
  return `${formatEuro(unitPrice)}/${baseUnit}`;
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

export interface LatLonPoint {
  lat: number;
  lon: number;
}

/** Great-circle distance between two coordinates in meters. */
export function haversineDistanceMeters(point1: LatLonPoint, point2: LatLonPoint): number {
  const R = 6371000;
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(point2.lat - point1.lat);
  const dLon = toRad(point2.lon - point1.lon);
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(toRad(point1.lat)) *
      Math.cos(toRad(point2.lat)) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

/** Formats straight-line distance from origin: «a 450 m» or «a 1,2 km». */
export function formatDistance(meters: number): string {
  if (!Number.isFinite(meters) || meters < 0) return "";
  if (meters < 1000) {
    return `a ${Math.round(meters)} m`;
  }
  const km = meters / 1000;
  const formatted = new Intl.NumberFormat("es-ES", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(km);
  return `a ${formatted} km`;
}

