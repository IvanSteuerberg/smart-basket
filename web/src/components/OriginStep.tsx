import { useState } from "react";
import { geocode, type GeocodeResult, type LatLon, type PriorityMode, type TravelMode } from "../api";
import { MapView } from "./MapView";
import { SearchBox } from "./SearchBox";

export interface RouteOptions {
  mode: TravelMode;
  maxStores: number;
  priority: PriorityMode;
  returnToOrigin: boolean;
}

export const DEFAULT_OPTIONS: RouteOptions = {
  mode: "walk",
  maxStores: 2,
  priority: "balanced",
  returnToOrigin: true,
};

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
  origin: LatLon | null;
  onOriginChange: (origin: LatLon) => void;
  options: RouteOptions;
  onOptionsChange: (patch: Partial<RouteOptions>) => void;
  onCalculate: () => void;
  onBack: () => void;
  calculating: boolean;
  error: string | null;
}

export function OriginStep({
  origin,
  onOriginChange,
  options,
  onOptionsChange,
  onCalculate,
  onBack,
  calculating,
  error,
}: OriginStepProps) {
  const [locationError, setLocationError] = useState<string | null>(null);

  function useMyLocation() {
    setLocationError(null);
    if (!navigator.geolocation) {
      setLocationError("No hemos podido obtener tu ubicación");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) =>
        onOriginChange({ lat: position.coords.latitude, lon: position.coords.longitude }),
      () => setLocationError("No hemos podido obtener tu ubicación"),
    );
  }

  return (
    <section className="card">
      <h2>¿Desde dónde sales?</h2>

      <MapView origin={origin} onPickOrigin={onOriginChange} />

      <button type="button" className="secondary" onClick={useMyLocation}>
        Usar mi ubicación
      </button>
      {locationError && (
        <p className="error" role="alert">
          {locationError}
        </p>
      )}

      <SearchBox<GeocodeResult>
        placeholder="Escribe una dirección de León"
        search={geocode}
        labelOf={(result) => result.label}
        keyOf={(result) => `${result.lat},${result.lon}`}
        onSelect={(result) => onOriginChange({ lat: result.lat, lon: result.lon })}
        minLength={3}
        onDemand
      />

      <div className="choice-row" role="group" aria-label="A pie o en coche">
        {MODES.map((mode) => (
          <label key={mode.value} className="choice">
            <input
              type="radio"
              name="mode"
              value={mode.value}
              checked={options.mode === mode.value}
              onChange={() => onOptionsChange({ mode: mode.value })}
            />
            {mode.label}
          </label>
        ))}
      </div>

      <label className="field">
        <span>Número máximo de tiendas</span>
        <select
          value={options.maxStores}
          onChange={(event) => onOptionsChange({ maxStores: Number(event.target.value) })}
        >
          {MAX_STORES.map((count) => (
            <option key={count} value={count}>
              {count}
            </option>
          ))}
        </select>
      </label>

      <div className="choice-row" role="group" aria-label="Prioridad">
        {PRIORITIES.map((priority) => (
          <label key={priority.value} className="choice">
            <input
              type="radio"
              name="priority"
              value={priority.value}
              checked={options.priority === priority.value}
              onChange={() => onOptionsChange({ priority: priority.value })}
            />
            {priority.label}
          </label>
        ))}
      </div>

      <label className="choice">
        <input
          type="checkbox"
          checked={options.returnToOrigin}
          onChange={(event) => onOptionsChange({ returnToOrigin: event.target.checked })}
        />
        Vuelvo al punto de salida
      </label>

      <button type="button" onClick={onCalculate} disabled={!origin || calculating}>
        Calcular cesta
      </button>
      {calculating && (
        <p className="muted" role="status">
          Calculando la mejor cesta…
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <button type="button" className="secondary" onClick={onBack}>
        Volver
      </button>
    </section>
  );
}
