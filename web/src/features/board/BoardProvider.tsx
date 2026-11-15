import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react';
import type { DrawShape } from '../../api/types';
import type { LngLat } from '../map/draw/geometry';
import type { Month, MonthRange } from '../calendar/months';
import type { AreaRef } from '../../config/types';
import { areaFlags, useConfig } from '../../config/context';
import {
  BoardContext,
  MAX_COMPARED_YEARS,
  type AiMap,
  type Board,
  type DrawnArea,
} from './context';

export function BoardProvider({ children }: { children: ReactNode }) {
  const config = useConfig();
  const [chosenArea, setAreaState] = useState<AreaRef | null>(null);
  const own = chosenArea ?? config?.default_area ?? null;
  const [polygon, setPolygon] = useState<readonly LngLat[] | null>(null);
  // the place the board showed before a drawn area: erasing the area brings it back
  const [before, setBefore] = useState<AreaRef | null>(null);
  // the live fires are asked by place, not by outline: on their tab an outline gives way to the place before it,
  // and the statistics find it again when they are back
  const [onFires, setOnFires] = useState(false);
  const outline = own !== null && 'polygon' in own;
  const place = before && !('polygon' in before) ? before : (config?.default_area ?? null);
  const area = onFires && outline ? place : own;
  const shownPolygon = onFires && outline ? null : polygon;
  const [drawn, setDrawnState] = useState<readonly DrawnArea[]>([]);
  const [range, setRangeState] = useState<MonthRange | null>(null);
  const [years, setYears] = useState<readonly number[]>([]);
  const [pick, setPickState] = useState<Month | null>(null);
  const [day, setDayState] = useState<string | null>(null);
  const [cluster, setClusterState] = useState<string | null>(null);
  const [clock, setClock] = useState<string | null>(null);
  const [check, setCheck] = useState(false);

  // what the assistant draws before the map is there is kept, in the order it came, until the map takes it
  const aiMap = useRef<AiMap | null>(null);
  const waiting = useRef<(() => void)[]>([]);
  const later = useCallback((job: (map: AiMap) => void) => {
    const map = aiMap.current;
    if (map) job(map);
    else
      waiting.current.push(() => {
        if (aiMap.current) job(aiMap.current);
      });
  }, []);
  const drawAi = useCallback(
    (shapes: readonly DrawShape[], replace: boolean) => {
      later((map) => {
        map.draw(shapes, replace);
      });
    },
    [later],
  );
  const clearAi = useCallback(() => {
    waiting.current = [];
    aiMap.current?.clear();
  }, []);
  const showShape = useCallback(
    (id: string) => {
      later((map) => {
        map.show(id);
      });
    },
    [later],
  );
  const bindAi = useCallback((map: AiMap | null) => {
    aiMap.current = map;
    if (!map) return;
    const jobs = waiting.current;
    waiting.current = [];
    for (const job of jobs) job();
  }, []);

  const value = useMemo<Board>(
    () => ({
      area,
      polygon: shownPolygon,
      drawn,
      years,
      range,
      pick,
      day,
      cluster,
      clock,
      check,
      // a place with the same record keeps the period, so places can be compared over it;
      // another record has other months, and the period starts over
      setArea: (next) => {
        const ref = typeof next === 'string' ? { id: next } : next;
        if (areaFlags(config, ref).covered !== areaFlags(config, area).covered) setRangeState(null);
        setAreaState(ref);
        setYears([]);
        setPolygon(
          'polygon' in ref && ref.polygon.type === 'Polygon'
            ? (ref.polygon.coordinates[0]?.map((point): LngLat => [point[0] ?? 0, point[1] ?? 0]) ??
                null)
            : null,
        );
        setPickState(null);
        setDayState(null);
        setClusterState(null);
        setClock(null);
        setCheck(false);
      },
      showDrawn: (corners) => {
        if (!drawn.some((item) => item.points === polygon)) setBefore(chosenArea);
        setAreaState({
          polygon: { type: 'Polygon', coordinates: [corners.map((point) => [...point])] },
        });
        setYears([]);
        setPolygon(corners);
        setPickState(null);
        setDayState(null);
        setClusterState(null);
        setClock(null);
        setCheck(false);
      },
      setDrawn: (next) => {
        setDrawnState(next);
        // the area on the calendar was erased from the map: back to the place shown before it
        if (outline && polygon !== null && !next.some((item) => item.points === polygon)) {
          setAreaState(before);
          setBefore(null);
          setPolygon(null);
          setPickState(null);
          setDayState(null);
          setClusterState(null);
          setClock(null);
        }
      },
      toggleYear: (year) => {
        setYears((now) =>
          now.includes(year)
            ? now.filter((item) => item !== year)
            : now.length < MAX_COMPARED_YEARS
              ? [...now, year].sort((a, b) => a - b)
              : now,
        );
        setPickState(null);
        setDayState(null);
        setClusterState(null);
        setClock(null);
        setCheck(false);
      },
      setRange: (next) => {
        setRangeState(next);
        setYears([]);
        setPickState(null);
        setDayState(null);
        setClusterState(null);
        setClock(null);
        setCheck(false);
      },
      // another month has other days
      setPick: (month) => {
        setPickState(month);
        setDayState(null);
        setClusterState(null);
        setClock(null);
      },
      setDay: (next) => {
        setDayState(next);
        setClusterState(null);
        setClock(null);
      },
      // another cluster has its own hours
      setCluster: (next) => {
        setClusterState(next);
        setClock(null);
      },
      setClock,
      setCheck,
      setOnFires,
      drawAi,
      clearAi,
      showShape,
      bindAi,
    }),
    [
      area,
      chosenArea,
      config,
      polygon,
      shownPolygon,
      outline,
      before,
      drawn,
      years,
      range,
      pick,
      day,
      cluster,
      clock,
      check,
      drawAi,
      clearAi,
      showShape,
      bindAi,
    ],
  );

  return <BoardContext value={value}>{children}</BoardContext>;
}
