import type { MessageKey } from '../../i18n/en';

export const BASEMAPS = ['map', 'sat', 'topo'] as const;
export type Basemap = (typeof BASEMAPS)[number];

export const BASEMAP_LABEL: Record<Basemap, MessageKey> = {
  map: 'map.base.map',
  sat: 'map.base.sat',
  topo: 'map.base.topo',
};

export const VECTOR_STYLE = 'https://tiles.openfreemap.org/styles/positron';

/** Raster layers drawn over the vector map; each is shown only for its own basemap. */
export const RASTER_LAYERS: Record<
  Exclude<Basemap, 'map'>,
  { sources: { id: string; tiles: string[]; maxzoom: number; attribution?: string }[] }
> = {
  sat: {
    sources: [
      {
        id: 'base-sat',
        tiles: [
          'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        ],
        maxzoom: 19,
        attribution: 'Imagery © Esri, Maxar, Earthstar Geographics',
      },
      {
        id: 'base-sat-labels',
        tiles: [
          'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
        ],
        maxzoom: 19,
      },
    ],
  },
  topo: {
    sources: [
      {
        id: 'base-topo',
        tiles: ['a', 'b', 'c'].map((s) => `https://${s}.tile.opentopomap.org/{z}/{x}/{y}.png`),
        maxzoom: 17,
        attribution: '© OpenTopoMap (CC-BY-SA)',
      },
    ],
  },
};

/** Southwest and northeast corners of a frame supplied by area data. */
export type Bounds = [[number, number], [number, number]];
