// Thin client of the HTTP API, the only contract with the backend (decision 0008).

export interface Health {
  status: "ok" | "degraded";
  version: string;
  engine_version: string;
  database: "ok" | "unavailable";
}

export async function getHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch("/api/health", { signal, headers: { Accept: "application/json" } });
  if (!response.ok && response.status !== 503) {
    throw new Error(`HTTP ${response.status}`);
  }
  return (await response.json()) as Health;
}
