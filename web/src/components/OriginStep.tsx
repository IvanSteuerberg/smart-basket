import { useId, useState } from "react";
import { geocode, type GeocodeResult, type LatLon, type PriorityMode, type TravelMode } from "../api";
import {
  DEFAULT_ROUTE_OPTIONS,
  type StoredOrigin,
  type StoredRouteOptions,
} from "../storage";
import { maxStoresLabel } from "../texts";
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

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-primary)]";
const BUTTON = `inline-flex min-h-11 items-center justify-center rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] px-4 text-[0.9375rem] font-semibold text-[var(--ink-primary)] transition-colors hover:border-[var(--accent-primary)] ${FOCUS}`;

/** One-line summary of the origin and the route options, shown while the step is folded. */
export function originSummary(origin: StoredOrigin, options: RouteOptions): string {
  const mode = MODES.find((candidate) => candidate.value === options.mode)?.label ?? "";
  return `Desde: ${origin.label} · ${mode} · ${maxStoresLabel(options.maxStores)}`;
}

/** Connected segmented control: a labelled group of toggle buttons, one pressed. */
function Segmented<T extends string | number>({
  label,
  choices,
  value,
  onChange,
}: {
  label: string;
  choices: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  const labelId = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <span id={labelId} className="text-[0.9375rem] font-semibold">
        {label}
      </span>
      <div
        role="group"
        aria-labelledby={labelId}
        className="flex rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-elevated)] p-0.5"
      >
        {choices.map((choice) => {
          const selected = choice.value === value;
          return (
            <button
              key={choice.value}
              type="button"
              aria-pressed={selected}
              onClick={() => onChange(choice.value)}
              className={`min-h-11 flex-1 rounded-[0.625rem] px-3 text-[0.9375rem] font-semibold tabular-nums transition-colors ${FOCUS} ${
                selected
                  ? "bg-[var(--accent-primary)] text-[var(--accent-on-primary)]"
                  : "text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]"
              }`}
            >
              {choice.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export interface OriginStepProps {
  origin: StoredOrigin | null;
  onOriginChange: (origin: StoredOrigin) => void;
  options: RouteOptions;
  onOptionsChange: (patch: Partial<RouteOptions>) => void;
  open: boolean;
  onToggleOpen: () => void;
}

/** Origin bar of the list screen: folded in one row once there is an origin, open otherwise. */
export function OriginStep({
  origin,
  onOriginChange,
  options,
  onOptionsChange,
  open,
  onToggleOpen,
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
    onOriginChange({ ...point, label: "Punto del mapa" });
  }

  // Folded view: only when there is already an origin and it is not explicitly open.
  if (!open && origin !== null) {
    return (
      <section
        aria-label="Punto de salida"
        className="flex items-center justify-between gap-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] p-3"
      >
        <p className="min-w-0 text-[0.9375rem] font-medium">{originSummary(origin, options)}</p>
        <button type="button" onClick={onToggleOpen} className={`${BUTTON} shrink-0`}>
          Cambiar
        </button>
      </section>
    );
  }

  return (
    <section
      aria-labelledby="origin-title"
      className="flex flex-col gap-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-card)] p-4"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="origin-title" className="text-[0.9375rem] font-bold">
          ¿Desde dónde sales?
        </h2>
        {origin && (
          <button type="button" onClick={onToggleOpen} className={BUTTON}>
            Cerrar
          </button>
        )}
      </div>

      <MapView origin={origin} onPickOrigin={handlePickMap} />

      <div className="flex flex-col gap-2">
        <button type="button" onClick={useMyLocation} className={BUTTON}>
          Usar mi ubicación
        </button>
        {locationError && (
          <p className="text-[0.8125rem] font-semibold text-[var(--danger-fg)]" role="alert">
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
          value={origin?.label}
          keepSelection
        />
      </div>

      <div className="flex flex-col gap-4 border-t border-[var(--border-subtle)] pt-4">
        <Segmented
          label="Cómo te desplazas"
          choices={MODES}
          value={options.mode}
          onChange={(mode) => onOptionsChange({ mode })}
        />
        <Segmented
          label="Número máximo de tiendas"
          choices={MAX_STORES.map((count) => ({ value: count, label: String(count) }))}
          value={options.maxStores}
          onChange={(maxStores) => onOptionsChange({ maxStores })}
        />
        <Segmented
          label="Prioridad"
          choices={PRIORITIES}
          value={options.priority}
          onChange={(priority) => onOptionsChange({ priority })}
        />

        <label className="flex min-h-11 cursor-pointer items-center gap-3 text-[0.9375rem]">
          <input
            type="checkbox"
            checked={options.returnToOrigin}
            onChange={(event) => onOptionsChange({ returnToOrigin: event.target.checked })}
            className="h-5 w-5 shrink-0"
          />
          Volver al punto de salida
        </label>
      </div>
    </section>
  );
}
