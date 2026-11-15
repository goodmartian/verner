import type { Map as MaplibreMap } from 'maplibre-gl';

/**
 * Runs the clean-up of a layer on a map that is still there. A map taken away already, or one whose style is gone, has nothing left to
 * clean, and a clean-up of an effect must never throw: it would take the whole block down with it.
 */
export function withMap(map: MaplibreMap, clean: () => void): void {
  if (!(map as { style?: unknown }).style) return;
  try {
    clean();
  } catch {
    // the map went while the clean-up ran: what it had on it went with it
  }
}
