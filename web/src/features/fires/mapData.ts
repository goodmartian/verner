import type { Feature, FeatureCollection, LineString, Point, Polygon } from 'geojson';
import type { AccessRoute, FireDetail, FireSummary, FirePlan } from '../../api/types';
import { bow, smoothPath, type LngLat } from '../map/draw/geometry';

type Features = FeatureCollection<LineString | Point | Polygon, Record<string, unknown>>;

const collection = (
  features: Feature<LineString | Point | Polygon, Record<string, unknown>>[],
): Features => ({
  type: 'FeatureCollection',
  features,
});

const point = (position: readonly number[], properties: Record<string, unknown>) =>
  ({
    type: 'Feature',
    properties,
    geometry: { type: 'Point', coordinates: [...position] },
  }) satisfies Feature<Point, Record<string, unknown>>;

const line = (path: readonly (readonly number[])[], properties: Record<string, unknown>) =>
  ({
    type: 'Feature',
    properties,
    geometry: { type: 'LineString', coordinates: path.map((p) => [...p]) },
  }) satisfies Feature<LineString, Record<string, unknown>>;

const polygon = (
  rings: readonly (readonly (readonly number[])[])[],
  properties: Record<string, unknown>,
) =>
  ({
    type: 'Feature',
    properties,
    geometry: { type: 'Polygon', coordinates: rings.map((ring) => ring.map((p) => [...p])) },
  }) satisfies Feature<Polygon, Record<string, unknown>>;

const toLngLat = (p: readonly number[]): LngLat => [p[0] ?? 0, p[1] ?? 0];

/** Arrowheads along a way: one every stretch of about 600 m, two at least, each turned to the way it sits on. */
function arrowheads(path: readonly (readonly number[])[], kind: string) {
  const cumulative = [0];
  for (let i = 1; i < path.length; i += 1) {
    const [x0 = 0, y0 = 0] = path[i - 1] ?? [];
    const [x1 = 0, y1 = 0] = path[i] ?? [];
    const lat = (y1 * Math.PI) / 180;
    cumulative.push((cumulative[i - 1] ?? 0) + Math.hypot((x1 - x0) * Math.cos(lat), y1 - y0));
  }
  const total = Math.max(cumulative.at(-1) ?? 0, 1e-9);
  const count = Math.max(2, Math.min(6, Math.round((total * 111) / 0.6)));
  const heads: Feature<Point, Record<string, unknown>>[] = [];
  for (let q = 1; q <= count; q += 1) {
    const at = (q / count) * total;
    const j = Math.max(
      1,
      cumulative.findIndex((length) => length >= at),
    );
    const [x0 = 0, y0 = 0] = path[j - 1] ?? [];
    const [x1 = 0, y1 = 0] = path[j] ?? [];
    const span = Math.max(1e-12, (cumulative[j] ?? 0) - (cumulative[j - 1] ?? 0));
    const f = (at - (cumulative[j - 1] ?? 0)) / span;
    const bearing =
      (Math.atan2((x1 - x0) * Math.cos((y1 * Math.PI) / 180), y1 - y0) * 180) / Math.PI;
    heads.push(point([x0 + (x1 - x0) * f, y0 + (y1 - y0) * f], { kind, b: bearing }));
  }
  return heads;
}

export interface FireMapInput {
  fires: readonly FireSummary[];
  selectedId: string | null;
  detail: FireDetail | null;
  plan: FirePlan | null;
  /** The way in, once the server has it. */
  access?: AccessRoute | null;
  /** The hours of the forecast front the player asks for; 0 shows none. */
  forecast: number;
}

/** Everything the fires put on the map, as one collection per layer. */
export function fireCollections({
  fires,
  selectedId,
  detail,
  plan,
  access,
  forecast,
}: FireMapInput) {
  const points = collection(
    fires.map((fire) =>
      point(fire.center, {
        id: fire.id,
        ha: fire.area_ha,
        selected: fire.id === selectedId,
      }),
    ),
  );

  const scar = collection(
    (detail?.scar ?? []).map((rings) =>
      polygon(
        rings.map((ring) => ring.map(toLngLat)),
        {},
      ),
    ),
  );
  const core = collection(
    (detail?.core ?? []).map((rings) =>
      polygon(
        rings.map((ring) => ring.map(toLngLat)),
        {},
      ),
    ),
  );
  // older passes are already the pale scar: only the last two keep their points, the last one the brighter
  const passIndex = detail?.pass_index ?? 0;
  const detections = collection(
    (detail?.detections ?? [])
      .filter((item) => item.pass_index >= passIndex - 1)
      .map((item) =>
        point(item.position, {
          pass: item.pass_index,
          now: item.pass_index === passIndex,
          frp: item.frp_mw,
        }),
      ),
  );
  const fronts =
    plan?.contours ?? detail?.spread?.contours.filter((item) => item.hours === forecast) ?? [];
  const contours = collection(
    fronts.flatMap((contour) =>
      contour.polygons.map((rings) => polygon(rings, { hours: contour.hours })),
    ),
  );

  // the road is drawn only when the server gave its line; the walk goes from where the road ends
  const road = access?.road_path;
  const accessLines = collection(
    access && road
      ? [
          line(road, { kind: 'road' }),
          ...(access.road_end_point
            ? [line([access.road_end_point, access.fire_edge_point], { kind: 'walk' })]
            : []),
        ]
      : [],
  );
  const accessStart = collection(
    access?.station_location && road ? [point(access.station_location, {})] : [],
  );

  const lines: Feature<LineString, Record<string, unknown>>[] = [];
  const zones: Feature<Polygon, Record<string, unknown>>[] = [];
  const pins: Feature<Point, Record<string, unknown>>[] = [];
  const heads: Feature<Point, Record<string, unknown>>[] = [];
  for (const crew of plan?.crews ?? []) {
    const blocked = crew.status === 'block';
    // the ways are drawn with soft bends
    const way = smoothPath(bow(crew.route.map(toLngLat)));
    lines.push(line(way, { kind: blocked ? 'blocked' : 'attack', crew: crew.number }));
    if (!blocked) {
      const out = smoothPath(bow(crew.escape.map(toLngLat)));
      lines.push(line(out, { kind: 'escape', crew: crew.number }));
      heads.push(...arrowheads(way, 'attack'), ...arrowheads(out, 'escape'));
    }
    // crews entering at one place share one dot
    const [x = 0, y = 0] = crew.entry;
    const shared = pins.some((pin) => {
      const [px = 0, py = 0] = pin.geometry.coordinates;
      return Math.hypot((px - x) * Math.cos((y * Math.PI) / 180), py - y) * 111_000 < 50;
    });
    if (!shared) pins.push(point(crew.entry, { kind: 'entry' }));
  }
  for (const zone of plan?.safe_zones ?? []) {
    zones.push(polygon([zone.map(toLngLat)], {}));
  }

  return {
    points,
    scar,
    core,
    detections,
    contours,
    access: accessLines,
    accessStart,
    planLines: collection(lines),
    planZones: collection(zones),
    planPins: collection(pins),
    planHeads: collection(heads),
  };
}
