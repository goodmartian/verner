import { act, renderHook } from '@testing-library/react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';
import { ConfigContext } from '../../config/context';
import { makeConfig, COUNTRY_ID } from '../../test/configFixtures';
import { BoardProvider } from '../board/BoardProvider';
import { useBoard, type DrawnArea } from '../board/context';
import type { LngLat } from './draw/geometry';
import { useFollowDrawn } from './useFollowDrawn';

const wrapper = ({ children }: { children: ReactNode }) => (
  <ConfigContext value={makeConfig()}>
    <BoardProvider>{children}</BoardProvider>
  </ConfigContext>
);

const ring = (x: number): LngLat[] => [
  [x, 0],
  [x + 1, 0],
  [x + 1, 1],
  [x, 0],
];

/** A map that keeps the listener of a press on the drawings, so a test can press. */
function fakeMap() {
  let press: ((event: unknown) => void) | null = null;
  const map = {
    on: (_type: string, _layer: string, listener: (event: unknown) => void) => {
      press = listener;
    },
    off: () => undefined,
  };
  return {
    map: map as unknown as MaplibreMap,
    press: (id: string) => {
      press?.({ features: [{ properties: { id } }] });
    },
  };
}

interface Props {
  on: boolean;
  areas: readonly DrawnArea[];
  asking: string | null;
  pan: boolean;
  map: MaplibreMap | null;
}

function setup(initial: Props) {
  return renderHook(
    (props: Props) => {
      useFollowDrawn(props.map, props.on, props.areas, props.asking, props.pan);
      return useBoard();
    },
    { wrapper, initialProps: initial },
  );
}

describe('the board follows the drawings on the calendar', () => {
  const u1: DrawnArea = { id: 'U1', points: ring(0), role: 'area' };
  const u2: DrawnArea = { id: 'U2', points: ring(5), role: 'area' };

  it('shows an area as soon as it is closed, and the next one when it is closed', () => {
    const { result, rerender } = setup({
      on: true,
      areas: [u1],
      asking: 'U1',
      pan: false,
      map: null,
    });
    expect(result.current.polygon).toBe(u1.points);
    rerender({ on: true, areas: [u1, u2], asking: 'U2', pan: false, map: null });
    expect(result.current.polygon).toBe(u2.points);
  });

  it('leaves the board alone on the fires and for a safe zone', () => {
    const { result, rerender } = setup({
      on: false,
      areas: [u1],
      asking: 'U1',
      pan: false,
      map: null,
    });
    expect(result.current.area).toEqual({ id: COUNTRY_ID });
    const safe: DrawnArea = { id: 'U2', points: ring(5), role: 'safe_zone' };
    rerender({ on: true, areas: [u1, safe], asking: 'U2', pan: false, map: null });
    expect(result.current.area).toEqual({ id: COUNTRY_ID });
  });

  it('does not show the same area again when its button is put away and comes back', () => {
    const { result, rerender } = setup({
      on: true,
      areas: [u1],
      asking: 'U1',
      pan: false,
      map: null,
    });
    act(() => {
      result.current.setArea(COUNTRY_ID);
    });
    rerender({ on: true, areas: [u1], asking: null, pan: false, map: null });
    rerender({ on: true, areas: [u1], asking: 'U1', pan: false, map: null });
    expect(result.current.area).toEqual({ id: COUNTRY_ID });
  });

  it('switches to another drawn area pressed with the hand tool, and only with it', () => {
    const { map, press } = fakeMap();
    const { result, rerender } = setup({
      on: true,
      areas: [u1, u2],
      asking: 'U2',
      pan: false,
      map,
    });
    expect(result.current.polygon).toBe(u2.points);
    act(() => {
      press('U1');
    });
    expect(result.current.polygon).toBe(u2.points);
    rerender({ on: true, areas: [u1, u2], asking: 'U2', pan: true, map });
    act(() => {
      press('U1');
    });
    expect(result.current.polygon).toBe(u1.points);
  });
});
