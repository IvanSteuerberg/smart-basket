import { divIcon, Icon, latLngBounds, type LatLngExpression } from "leaflet";
import "leaflet/dist/leaflet.css";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";
import { useEffect } from "react";
import { MapContainer, Marker, Polyline, TileLayer, useMap, useMapEvents } from "react-leaflet";
import type { BasketStore, LatLon } from "../api";

// Leaflet's default icons point at image paths that Vite does not serve (decision 0008).
Icon.Default.mergeOptions({
  iconUrl: markerIcon,
  iconRetinaUrl: markerIcon2x,
  shadowUrl: markerShadow,
});

const LEON: LatLon = { lat: 42.5987, lon: -5.5671 };
const LEON_ZOOM = 14;

export interface MapViewProps {
  origin: LatLon | null;
  onPickOrigin?: (point: LatLon) => void;
  stores?: BasketStore[];
  route?: [number, number][];
  fitContent?: boolean;
}

function toPosition(point: LatLon): LatLngExpression {
  return [point.lat, point.lon];
}

function OriginClicker({ onPick }: { onPick: (point: LatLon) => void }) {
  useMapEvents({
    click(event) {
      onPick({ lat: event.latlng.lat, lon: event.latlng.lng });
    },
  });
  return null;
}

/** Keeps the origin visible when it comes from an address or the browser. */
function FollowOrigin({ origin }: { origin: LatLon | null }) {
  const map = useMap();
  useEffect(() => {
    if (!origin) return;
    const point: [number, number] = [origin.lat, origin.lon];
    if (!map.getBounds().pad(-0.25).contains(point)) {
      map.setView(point, Math.max(map.getZoom(), LEON_ZOOM + 1));
    }
  }, [map, origin]);
  return null;
}

function FitContent({
  origin,
  stores,
  route,
}: {
  origin: LatLon | null;
  stores: BasketStore[];
  route: [number, number][];
}) {
  const map = useMap();
  useEffect(() => {
    const points: [number, number][] = [];
    if (origin) points.push([origin.lat, origin.lon]);
    for (const store of stores) points.push([store.lat, store.lon]);
    points.push(...route);
    if (points.length === 0) return;
    map.fitBounds(latLngBounds(points), { padding: [24, 24], maxZoom: 16 });
  }, [map, origin, stores, route]);
  return null;
}

function storeIcon(position: number) {
  return divIcon({
    className: "store-pin",
    html: `<span>${position}</span>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

/** OpenStreetMap map with the origin, the stores of the basket and its route. */
export function MapView({
  origin,
  onPickOrigin,
  stores = [],
  route = [],
  fitContent = false,
}: MapViewProps) {
  return (
    <MapContainer
      center={toPosition(LEON)}
      zoom={LEON_ZOOM}
      className="map"
      scrollWheelZoom={false}
    >
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      />
      {onPickOrigin && <OriginClicker onPick={onPickOrigin} />}
      <FollowOrigin origin={origin} />
      {origin && <Marker position={toPosition(origin)} />}
      {stores.map((store) => (
        <Marker
          key={store.store_id}
          position={[store.lat, store.lon]}
          icon={storeIcon(store.position)}
        />
      ))}
      {route.length > 1 && (
        <Polyline positions={route} pathOptions={{ color: "#2f6f4e", weight: 4 }} />
      )}
      {fitContent && <FitContent origin={origin} stores={stores} route={route} />}
    </MapContainer>
  );
}
