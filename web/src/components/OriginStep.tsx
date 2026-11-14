import { useState } from "react";
import { geocode, type GeocodeResult, type LatLon, type PriorityMode, type TravelMode } from "../api";
import {
  DEFAULT_ROUTE_OPTIONS,
  type StoredOrigin,
  type StoredRouteOptions,
} from "../storage";
import { MapView } from "./MapView";
import { SearchBox } from "./SearchBox";

export type RouteOptions = StoredRouteOptions;
export const DEFAULT_OPTIONS = DEFAULT_ROUTE_OPTIONS;

const MAX_STORES = [1, 2, 3];

const MODES: { value: TravelMode; label: string }[] = [
  { value: "walk", label: "A pie" },
  { value: "car", label: "En coche" },
];

const PRIORITIES: { value: PriorityMode; label: string }[] = [
  { value: "savings", label: "Ahorrar" },
  { value: "balanced", label: "Equilibrado" },
  { value: "time", label: "Tiempo" },
];

export interface OriginStepProps {
  origin: StoredOrigin | null;
  onOriginChange: (origin: StoredOrigin) => void;
  options: RouteOptions;
  onOptionsChange: (patch: Partial<RouteOptions>) => void;
  open: boolean;
  onToggleOpen: () => void;
  onCalculate?: () => void;
  calculating?: boolean;
}

export function OriginStep({
  origin,
  onOriginChange,
  options,
  onOptionsChange,
  open,
  onToggleOpen,
  onCalculate,
  calculating,
}: OriginStepProps) {
  const [locationError, setLocationError] = useState<string | null>(null);

  function useMyLocation() {
    setLocationError(null);
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setLocationError("No hemos podido obtener tu ubicación");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) =>
        onOriginChange({
          lat: position.coords.latitude,
          lon: position.coords.longitude,
          label: "Mi ubicación",
        }),
      () => setLocationError("No hemos podido obtener tu ubicación"),
    );
  }

  function handlePickMap(point: LatLon) {
    onOriginChange({
      ...point,
      label: "Punto del mapa",
    });
  }

  // Folded view: only when there is already an origin and not explicitly open.
  if (!open && origin !== null) {
    const modeLabel = options.mode === "walk" ? "A pie" : "En coche";
    return (
      <section className="flex items-center justify-between gap-3 rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
        <p className="min-w-0 text-sm font-medium text-slate-800">
          Desde: <span className="font-semibold text-slate-900">{origin.label}</span> · {modeLabel} · Hasta {options.maxStores} tiendas
        </p>
        <button
          type="button"
          onClick={onToggleOpen}
          className="shrink-0 rounded-xl border border-brand px-3.5 py-1.5 text-xs font-semibold text-brand hover:bg-brand-soft"
        >
          Cambiar
        </button>
      </section>
    );
  }

  return (
    <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-base font-bold text-slate-900">¿Desde dónde sales?</h2>
        {origin && (
          <button
            type="button"
            onClick={onToggleOpen}
            className="rounded-lg px-2 py-1 text-xs font-semibold text-stone-500 hover:text-slate-800"
          >
            Cerrar
          </button>
        )}
      </div>

      <MapView origin={origin} onPickOrigin={handlePickMap} />

      <div className="mt-3 flex flex-col gap-2">
        <button
          type="button"
          onClick={useMyLocation}
          className="w-full rounded-xl border border-brand py-2 text-sm font-semibold text-brand hover:bg-brand-soft"
        >
          Usar mi ubicación
        </button>
        {locationError && (
          <p className="text-xs font-semibold text-price" role="alert">
            {locationError}
          </p>
        )}

        <SearchBox<GeocodeResult>
          placeholder="Escribe una dirección de León"
          search={geocode}
          labelOf={(result) => result.label}
          keyOf={(result) => `${result.lat},${result.lon}`}
          onSelect={(result) =>
            onOriginChange({ lat: result.lat, lon: result.lon, label: result.label })
          }
          minLength={3}
          onDemand
        />
      </div>

      <div className="mt-4 flex flex-col gap-3 border-t border-stone-100 pt-3 text-sm">
        <div className="grid grid-cols-2 gap-2" role="group" aria-label="A pie o en coche">
          {MODES.map((mode) => (
            <label
              key={mode.value}
              className={`flex cursor-pointer items-center justify-center gap-2 rounded-xl border p-2 font-medium transition-colors ${
                options.mode === mode.value
                  ? "border-brand bg-brand-soft text-brand-dark"
                  : "border-stone-200 bg-stone-50 text-stone-600 hover:bg-stone-100"
              }`}
            >
              <input
                type="radio"
                name="mode"
                value={mode.value}
                checked={options.mode === mode.value}
                onChange={() => onOptionsChange({ mode: mode.value })}
                className="accent-brand"
              />
              {mode.label}
            </label>
          ))}
        </div>

        <label className="flex items-center justify-between gap-2 text-stone-600">
          <span>Número máximo de tiendas</span>
          <select
            value={options.maxStores}
            onChange={(event) => onOptionsChange({ maxStores: Number(event.target.value) })}
            className="rounded-xl border border-stone-200 bg-white px-3 py-1.5 text-slate-900 outline-none focus:border-brand"
          >
            {MAX_STORES.map((count) => (
              <option key={count} value={count}>
                {count}
              </option>
            ))}
          </select>
        </label>

        <div className="grid grid-cols-3 gap-2" role="group" aria-label="Prioridad">
          {PRIORITIES.map((priority) => (
            <label
              key={priority.value}
              className={`flex cursor-pointer items-center justify-center gap-1.5 rounded-xl border p-2 text-xs font-medium transition-colors ${
                options.priority === priority.value
                  ? "border-brand bg-brand-soft text-brand-dark"
                  : "border-stone-200 bg-stone-50 text-stone-600 hover:bg-stone-100"
              }`}
            >
              <input
                type="radio"
                name="priority"
                value={priority.value}
                checked={options.priority === priority.value}
                onChange={() => onOptionsChange({ priority: priority.value })}
                className="accent-brand"
              />
              {priority.label}
            </label>
          ))}
        </div>

        <label className="flex cursor-pointer items-center gap-2 text-stone-700">
          <input
            type="checkbox"
            checked={options.returnToOrigin}
            onChange={(event) => onOptionsChange({ returnToOrigin: event.target.checked })}
            className="accent-brand h-4 w-4 rounded"
          />
          Vuelvo al punto de salida
        </label>

        {onCalculate && (
          <button
            type="button"
            onClick={onCalculate}
            disabled={!origin || calculating}
            className="mt-2 w-full rounded-2xl bg-brand py-2.5 text-center text-sm font-bold text-white shadow-xs transition-colors hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-50"
          >
            Calcular cesta
          </button>
        )}
      </div>
    </section>
  );
}
