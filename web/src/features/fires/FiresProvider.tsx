import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react';
import type { FirePlan } from '../../api/types';
import type { LngLat } from '../map/draw/geometry';
import {
  FiresContext,
  MAX_CREWS,
  type Brief,
  type Fires,
  type Hours,
  type Mark,
  type MarksApi,
} from './context';
import type { MarkKind } from './context';
import { areaId } from '../../config/context';
import { useBoard } from '../board/context';
import type { PlanRecord } from '../../api/types';
import { planSignature } from './planSignature';

const FRESH: Brief = { crews: 2, hours: 3, marks: [], area: null, overrides: [] };

/** A point as the server writes it, as a point of the map. */
const corner = (point: readonly number[]): LngLat => [point[0] ?? 0, point[1] ?? 0];

export function FiresProvider({ children }: { children: ReactNode }) {
  // `?demo=1` opens the example fires of February 2022 at once
  const [demo, setDemo] = useState(
    () => new URLSearchParams(window.location.search).get('demo') === '1',
  );
  const [fireId, setFireId] = useState<string | null>(null);
  const [pass, setPassState] = useState<number | null>(null);
  const [brief, setBrief] = useState<Brief>(FRESH);
  const [placing, setPlacing] = useState<MarkKind | null>(null);
  const [forecast, setForecast] = useState<0 | 1 | 3 | 6>(0);
  const [clock, setClockState] = useState<string | null>(null);
  const [player, setPlayer] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [plan, setPlan] = useState<FirePlan | null>(null);
  const [record, setRecord] = useState<PlanRecord | null>(null);
  const [dock, setDock] = useState(false);
  const [cover, setCover] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const marksApi = useRef<MarksApi | null>(null);
  const [crewHi, setCrewHi] = useState(0);
  const [crewFocus, setCrewFocus] = useState<{ crew: number } | null>(null);

  // another region has other fires: the choice, the plan and the player of the old one are let go
  const region = areaId(useBoard().area);
  const [seenRegion, setSeenRegion] = useState(region);
  if (seenRegion !== region) {
    setSeenRegion(region);
    setFireId(null);
    setPassState(null);
    setClockState(null);
    setForecast(0);
    setHovered(null);
    setBrief((now) => ({ ...FRESH, marks: now.marks }));
    setPlacing(null);
    setPlanning(false);
    setPlan(null);
    setRecord(null);
    setDock(false);
    setCrewFocus(null);
    setSaved(null);
    setCover(false);
    setPlayer(false);
  }

  // these two are called from effects of the map: they keep their identity, or the effect would call them again
  const setMarks = useCallback((marks: readonly Mark[]) => {
    setBrief((now) => ({ ...now, marks }));
  }, []);
  const bindMarks = useCallback((api: MarksApi | null) => {
    marksApi.current = api;
  }, []);

  const value = useMemo<Fires>(() => {
    const change = (patch: Partial<Brief>) => {
      setBrief((now) => ({ ...now, ...patch }));
    };
    return {
      demo,
      // the example and the live fires are different lists
      setDemo: (next) => {
        setDemo(next);
        setFireId(null);
        setPassState(null);
        setClockState(null);
        setBrief((now) => ({ ...FRESH, marks: now.marks }));
        setPlan(null);
        setRecord(null);
        setDock(false);
        setCrewFocus(null);
        setSaved(null);
        setCover(false);
      },
      fireId,
      hovered,
      setHovered,
      select: (id) => {
        setFireId(id);
        setPassState(null);
        setClockState(null);
        setForecast(0);
        setHovered(null);
        setBrief((now) => ({ ...FRESH, marks: now.marks }));
        setPlacing(null);
        setPlanning(false);
        setPlan(null);
        setRecord(null);
        setDock(false);
        setCrewFocus(null);
        setSaved(null);
        setCover(false);
      },
      pass,
      setPass: (next) => {
        setPassState(next);
        setClockState(null);
        setForecast(0);
      },
      clock,
      setClock: (next) => {
        setClockState(next);
        setForecast(0);
      },
      brief,
      setCrews: (crews) => {
        change({ crews: Math.min(MAX_CREWS, Math.max(1, crews)) });
      },
      setHours: (hours: Hours) => {
        change({ hours });
      },
      setMarks,
      clearMarks: (kind: MarkKind) => {
        marksApi.current?.clear(kind);
      },
      bindMarks,
      setArea: (area: readonly LngLat[] | null) => {
        change({ area });
      },
      toggleOverride: (key: string) => {
        setBrief((now) => ({
          ...now,
          overrides: now.overrides.includes(key)
            ? now.overrides.filter((item) => item !== key)
            : [...now.overrides, key],
        }));
      },
      placing,
      setPlacing,
      forecast,
      setForecast,
      player,
      setPlayer: (next) => {
        setPlayer(next);
        if (!next) setClockState(null);
      },
      planning,
      setPlanning,
      plan,
      setPlan,
      dock,
      setDock,
      crewHi,
      setCrewHi,
      crewFocus,
      focusCrew: (crew) => {
        setCrewFocus({ crew });
      },
      cover,
      setCover,
      saved,
      setSaved,
      record,
      openRecord: (next) => {
        setDemo(next.plan.source === 'demo');
        setFireId(next.plan.fire_id);
        setPassState(next.plan.pass_index);
        setClockState(null);
        const marks: Mark[] = (next.request.marks ?? []).map((mark) => ({
          kind: mark.kind,
          position: corner(mark.position),
        }));
        // the marks of that plan go on the map, where they can be moved
        marksApi.current?.load(marks);
        setBrief({
          crews: next.request.crews,
          hours: next.request.hours,
          marks,
          area: next.request.area?.map(corner) ?? null,
          overrides: next.request.overrides ?? [],
        });
        setPlan(next.plan);
        setRecord(next);
        setSaved(planSignature(next.plan));
        setPlanning(false);
        setDock(true);
        setPlacing(null);
      },
    };
  }, [
    demo,
    fireId,
    pass,
    clock,
    brief,
    placing,
    forecast,
    player,
    planning,
    plan,
    record,
    dock,
    crewHi,
    crewFocus,
    saved,
    cover,
    hovered,
    setMarks,
    bindMarks,
  ]);

  return <FiresContext value={value}>{children}</FiresContext>;
}
