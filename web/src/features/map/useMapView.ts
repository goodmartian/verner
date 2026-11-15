import { AttributionControl, Map as MaplibreMap, setWorkerUrl } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { useEffect, useRef, useState } from 'react';
import { RASTER_LAYERS, VECTOR_STYLE, type Basemap, type Bounds } from './basemaps';
import { fitPadding, type MapPadding } from './framing';

// the worker is bundled with its imports, so it also loads from the built app
setWorkerUrl(workerUrl);

const rasterIds = (basemap: Exclude<Basemap, 'map'>) =>
  RASTER_LAYERS[basemap].sources.map((source) => source.id);

/** Creates the map in the container, keeps it sized and shows the chosen basemap. */
export function useMapView(basemap: Basemap, padding: MapPadding, bounds: Bounds | undefined) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MaplibreMap | null>(null);
  // what the map frames now, kept for the moments it changes size
  const frame = useRef({ bounds, padding });
  // set once the style has loaded: layers and tools can only be added from then on
  const [loaded, setLoaded] = useState<MaplibreMap | null>(null);
  const ready = bounds !== undefined;

  useEffect(() => {
    if (!container.current || !ready) return;
    const instance = new MaplibreMap({
      container: container.current,
      style: VECTOR_STYLE,
      attributionControl: false,
      // north stays up: a rotated map would draw the rectangles of the drawing tools at a slant
      dragRotate: false,
      pitchWithRotate: false,
      touchPitch: false,
      maxPitch: 0,
    });
    instance.touchZoomRotate.disableRotation();
    instance.keyboard.disableRotation();
    instance.addControl(new AttributionControl({ compact: true }), 'bottom-left');
    // the credits show as the (i) button and open on a click, also after the map is resized
    const collapseCredits = () => {
      const credit = instance.getContainer().querySelector('.maplibregl-ctrl-attrib');
      credit?.classList.remove('maplibregl-compact-show');
      credit?.removeAttribute('open');
    };
    collapseCredits();
    instance.on('resize', collapseCredits);
    instance.on('load', () => {
      collapseCredits();
      for (const { sources } of Object.values(RASTER_LAYERS)) {
        for (const { id, ...source } of sources) {
          instance.addSource(id, { type: 'raster', tileSize: 256, ...source });
          instance.addLayer({ id, type: 'raster', source: id, layout: { visibility: 'none' } });
        }
      }
      setLoaded(instance);
    });
    // the window changed size: the map is drawn again and frames the region again
    const resize = new ResizeObserver(() => {
      instance.resize();
      const size = instance.getContainer();
      if (frame.current.bounds)
        instance.fitBounds(frame.current.bounds, {
          padding: fitPadding(frame.current.padding, size.clientWidth, size.clientHeight),
          duration: 0,
        });
    });
    resize.observe(container.current);
    map.current = instance;
    return () => {
      resize.disconnect();
      // the layers of the screen take their own parts off in the same sweep: the map goes after them
      window.setTimeout(() => {
        instance.remove();
      }, 0);
      map.current = null;
      setLoaded(null);
    };
  }, [ready]);

  useEffect(() => {
    const instance = map.current;
    if (!loaded || !instance) return;
    for (const name of ['sat', 'topo'] as const) {
      for (const id of rasterIds(name)) {
        instance.setLayoutProperty(id, 'visibility', name === basemap ? 'visible' : 'none');
      }
    }
  }, [loaded, basemap]);

  useEffect(() => {
    frame.current = { bounds, padding };
    const instance = map.current;
    if (!instance || !bounds) return;
    const size = instance.getContainer();
    instance.fitBounds(bounds, {
      padding: fitPadding(padding, size.clientWidth, size.clientHeight),
      duration: 0,
    });
  }, [padding, bounds]);

  return {
    container,
    map: loaded,
    zoomIn: () => map.current?.zoomIn(),
    zoomOut: () => map.current?.zoomOut(),
  };
}
