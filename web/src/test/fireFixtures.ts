import { INTEGER_ZONE } from './configFixtures';
import type {
  FireDetail,
  FireList,
  FireSummary,
  FirePlan,
  PlanRecord,
  AccessRoute,
} from '../api/types';

export const FIRE: FireSummary = {
  timezone: INTEGER_ZONE,
  id: '20261028-1',
  center: [-56.09, -28.455],
  nearest_place: {
    name: 'Santo Tomé',
    distance_km: 11.7,
    location: [-56.035, -28.55],
    direction: 7,
  },
  detection_count: 35,
  area_ha: 252,
  first_detection_at: '2026-10-28T16:37:00Z',
  last_detection_at: '2026-10-28T18:38:00Z',
  growth: [
    {
      pass_index: 0,
      time: '2026-10-28T04:34:00Z',
      detections: 0,
      pass_detections: 0,
      area_ha: 0,
      frp_mw: 0,
    },
    {
      pass_index: 1,
      time: '2026-10-28T18:38:00Z',
      detections: 35,
      pass_detections: 35,
      area_ha: 252,
      frp_mw: 652,
    },
  ],
};

export const OTHER_FIRE: FireSummary = {
  ...FIRE,
  id: '20261027-4',
  nearest_place: { ...FIRE.nearest_place, name: 'Villa General Savio', direction: 0 },
  area_ha: 210,
};

export const FIRE_LIST: FireList = {
  source: 'live',
  available: true,
  updated_at: '2026-10-29T14:57:00Z',
  days: ['2026-10-27', '2026-10-28', '2026-10-29'],
  passes: [
    { index: 0, time: '2026-10-28T04:34:00Z', detection_count: 34 },
    { index: 1, time: '2026-10-28T18:38:00Z', detection_count: 128 },
  ],
  fires: [FIRE, OTHER_FIRE],
  attribution: 'Fire data: NASA FIRMS',
};

export const EMPTY_FIRE_LIST: FireList = {
  ...FIRE_LIST,
  days: [],
  passes: [],
  fires: [],
  updated_at: null,
  attribution: null,
};

export const FIRE_DETAIL: FireDetail = {
  timezone: INTEGER_ZONE,
  source: 'live',
  summary: FIRE,
  pass_index: 1,
  pass_time: '2026-10-28T18:38:00Z',
  detections: [{ position: [-56.099, -28.46], pass_index: 1, frp_mw: 14.2 }],
  outline: [
    [-56.1, -28.455],
    [-56.1, -28.463],
    [-56.09, -28.463],
  ],
  scar: [
    [
      [
        [-56.0908, -28.4637],
        [-56.0896, -28.4637],
        [-56.0896, -28.4625],
        [-56.0908, -28.4637],
      ],
    ],
  ],
  core: null,
  spread: {
    rate_m_per_h: 1000,
    observed: false,
    rate_source: 'weather',
    rate_weather_m_per_h: 1000,
    rate_measured_m_per_h: null,
    length_to_breadth: 4.4,
    wind: {
      speed_kmh: 10,
      from_deg: 163,
      temperature_c: 16.8,
      humidity_pct: 72,
      at: '2026-10-28T18:00:00Z',
    },
    contours: [
      {
        hours: 1,
        polygons: [
          [
            [
              [-56.102, -28.45],
              [-56.1, -28.463],
              [-56.09, -28.463],
              [-56.102, -28.45],
            ],
          ],
        ],
        area_ha: 523,
      },
    ],
    current_area_ha: 408,
  },
  weather: {
    source: 'point',
    start: '2026-10-28T00:00:00Z',
    wind_speed_kmh: Array.from({ length: 48 }, () => 10),
    wind_from_deg: Array.from({ length: 48 }, () => 163),
    temperature_c: Array.from({ length: 48 }, () => 16.8),
    humidity_pct: Array.from({ length: 48 }, () => 72),
  },
  detections_by_day: { '2026-10-28': 35 },
  attribution: 'Fire data: NASA FIRMS',
};

const NO_ISSUE = {
  crew: null,
  mark: null,
  hours: null,
  speed_kmh: null,
  count: null,
  until_min: null,
  walk_min: null,
  distance_m: null,
  key: null,
  forced: null,
  hot_spot: null,
  crews: null,
  hot_spots: null,
} as const;

export const PLAN: FirePlan = {
  source: 'live',
  fire_id: FIRE.id,
  pass_index: 1,
  pass_time: '2026-10-28T18:38:00Z',
  hours: 3,
  wind: { speed_kmh: 10, from_deg: 163, at: '2026-10-28T18:00:00Z' },
  contours: FIRE_DETAIL.spread?.contours ?? [],
  entry: { position: [-56.08, -28.466], from_direction: 4 },
  flanks: [
    {
      side: 0,
      line: [
        [-56.08, -28.466],
        [-56.085, -28.464],
      ],
      length_m: 1400,
      reach_h: null,
    },
  ],
  safe_zone: { position: [-56.08, -28.467], distance_m: 85, on_burned_ground: false },
  safe_zones: [],
  hot_spots: [],
  crews: [
    {
      number: 1,
      side: 0,
      entry: [-56.08, -28.466],
      entry_source: 'planner',
      entry_mark: null,
      hot_mark: null,
      work_point: [-56.085, -28.464],
      route: [
        [-56.08, -28.466],
        [-56.085, -28.464],
      ],
      walk_min: 12,
      leave_in_h: 2.5,
      escape: [
        [-56.085, -28.464],
        [-56.08, -28.466],
      ],
      safe_point: [-56.08, -28.467],
      safe_distance_m: 85,
      safe_on_burned_ground: false,
      status: 'ok',
      target: { kind: 'hot', hot_spot: 1, chosen_by_planner: true },
      entry_forced: false,
      on_trail: false,
      crosses_wet_ground: false,
      length_m: 600,
      long_walk: false,
      distance_to_active_m: null,
      escape_threatened_in_h: null,
      held: [],
      land: [
        { id: 1, share_pct: 62 },
        { id: 3, share_pct: 38 },
      ],
    },
    {
      number: 2,
      side: null,
      entry: [-56.09, -28.47],
      entry_source: 'op',
      entry_mark: 1,
      hot_mark: 1,
      work_point: [-56.09, -28.465],
      route: [
        [-56.09, -28.47],
        [-56.09, -28.465],
      ],
      walk_min: 20,
      leave_in_h: null,
      escape: [
        [-56.09, -28.465],
        [-56.09, -28.47],
      ],
      safe_point: [-56.09, -28.471],
      safe_distance_m: 60,
      safe_on_burned_ground: true,
      status: 'block',
      target: { kind: 'hot', hot_spot: 1, chosen_by_planner: true },
      entry_forced: false,
      on_trail: false,
      crosses_wet_ground: false,
      length_m: 600,
      long_walk: false,
      distance_to_active_m: null,
      escape_threatened_in_h: null,
      held: ['fc'],
      land: null,
    },
  ],
  hot_marks: [{ number: 1, position: [-56.09, -28.465] }],
  rejected_entries: [],
  issues: [
    { ...NO_ISSUE, level: 'block', kind: 'fc', crew: 2, mark: 1, hours: 1.5, key: 'e1' },
    { ...NO_ISSUE, level: 'info', kind: 'stale' },
  ],
  report: {
    area_ha: 252,
    detections_last_pass: 35,
    last_pass: 1,
    hot_spots: [1],
    all_on_burned_ground: false,
    spread_km_per_h: 1,
    growth_ha: 252,
    leave_in_h: 2.5,
    safe_min_m: 60,
    safe_max_m: 85,
  },
  nearest_place: null,
  straight_line_only: false,
  attribution: null,
};

export const PLAN_RECORD: PlanRecord = {
  id: 7,
  fire_id: '20261028-1',
  title: 'Santo Tomé, 2 crews, 3 h',
  created_at: '2026-10-29T15:00:00Z',
  request: { pass: null, crews: 2, hours: 3, marks: [], area: null },
  plan: PLAN,
  fire: FIRE_DETAIL,
};

export const ACCESS_ROUTE: AccessRoute = {
  origin_kind: 'place',
  origin_source: 'place',
  route_source: 'osrm',
  station_name: 'Villa Ocampo',
  station_location: [-56.049, -28.55],
  drive_min: 77,
  drive_km: 30.6,
  walk_km: 4.4,
  walk_min: 74.5,
  total_min: 151.5,
  fire_edge_point: [-56.0794, -28.464],
  road_end_point: [-56.0791, -28.466],
  road_path: [
    [-56.0495, -28.5508],
    [-56.0791, -28.466],
  ],
  attribution: '© OpenStreetMap contributors, OSRM',
};
