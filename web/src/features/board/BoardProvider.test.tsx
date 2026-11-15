import { ConfigContext } from '../../config/context';
import { makeConfig, COUNTRY_ID, REGION_ID } from '../../test/configFixtures';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import type { LngLat } from '../map/draw/geometry';
import { BoardProvider } from './BoardProvider';
import type { DrawShape } from '../../api/types';
import { MAX_COMPARED_YEARS, useBoard, type AiMap } from './context';

const wrapper = ({ children }: { children: ReactNode }) => (
  <ConfigContext value={makeConfig()}>
    <BoardProvider>{children}</BoardProvider>
  </ConfigContext>
);
const setup = () => renderHook(() => useBoard(), { wrapper });

describe('the years side by side', () => {
  it('are added and taken out by a click on the year, kept in order', () => {
    const { result } = setup();
    act(() => {
      result.current.toggleYear(2022);
      result.current.toggleYear(2020);
    });
    expect(result.current.years).toEqual([2020, 2022]);
    act(() => {
      result.current.toggleYear(2022);
    });
    expect(result.current.years).toEqual([2020]);
  });

  it('are at most as many as there are lines to draw', () => {
    const { result } = setup();
    for (let year = 2010; year < 2010 + MAX_COMPARED_YEARS + 2; year += 1) {
      act(() => {
        result.current.toggleYear(year);
      });
    }
    expect(result.current.years).toHaveLength(MAX_COMPARED_YEARS);
  });

  it('are let go when a period, a place or a drawn area is chosen', () => {
    const { result } = setup();
    act(() => {
      result.current.toggleYear(2020);
      result.current.toggleYear(2021);
    });
    act(() => {
      result.current.setRange({ from: '2024-01', to: '2024-12' });
    });
    expect(result.current.years).toEqual([]);
    act(() => {
      result.current.toggleYear(2020);
    });
    act(() => {
      result.current.setArea(REGION_ID);
    });
    expect(result.current.years).toEqual([]);
  });
});

describe('the drawn areas', () => {
  const square: LngLat[] = [
    [0, 0],
    [1, 0],
    [1, 1],
  ];

  it('send the board back to the country when the area on the calendar is erased', () => {
    const { result } = setup();
    const corners = [...square];
    act(() => {
      result.current.setDrawn([{ id: 'U1', points: corners, role: 'area' }]);
      result.current.showDrawn(corners);
    });
    expect(result.current.area).toHaveProperty('polygon');
    act(() => {
      result.current.setDrawn([]);
    });
    expect(result.current.area).toEqual({ id: COUNTRY_ID });
    expect(result.current.polygon).toBeNull();
  });

  it('send the board back to the place it showed before them, however many were shown', () => {
    const { result } = setup();
    const first = [...square];
    const second = [...square];
    act(() => {
      result.current.setArea(REGION_ID);
    });
    act(() => {
      result.current.setDrawn([{ id: 'U1', points: first, role: 'area' }]);
      result.current.showDrawn(first);
    });
    act(() => {
      result.current.setDrawn([
        { id: 'U1', points: first, role: 'area' },
        { id: 'U2', points: second, role: 'area' },
      ]);
    });
    act(() => {
      result.current.showDrawn(second);
    });
    expect(result.current.polygon).toBe(second);
    act(() => {
      result.current.setDrawn([{ id: 'U1', points: first, role: 'area' }]);
    });
    expect(result.current.area).toEqual({ id: REGION_ID });
    expect(result.current.polygon).toBeNull();
  });

  it('give way to the place before them on the fires, and come back on the statistics', () => {
    const { result } = setup();
    const corners = [...square];
    act(() => {
      result.current.setArea(REGION_ID);
    });
    act(() => {
      result.current.setDrawn([{ id: 'U1', points: corners, role: 'area' }]);
      result.current.showDrawn(corners);
    });
    act(() => {
      result.current.setOnFires(true);
    });
    expect(result.current.area).toEqual({ id: REGION_ID });
    expect(result.current.polygon).toBeNull();
    act(() => {
      result.current.setOnFires(false);
    });
    expect(result.current.area).toHaveProperty('polygon');
    expect(result.current.polygon).toBe(corners);
  });

  it('give way to the country on the fires when nothing was chosen before them', () => {
    const { result } = setup();
    const corners = [...square];
    act(() => {
      result.current.setDrawn([{ id: 'U1', points: corners, role: 'area' }]);
      result.current.showDrawn(corners);
      result.current.setOnFires(true);
    });
    expect(result.current.area).toEqual({ id: COUNTRY_ID });
  });

  it('keep the board where it is when another area is erased', () => {
    const { result } = setup();
    const shown = [...square];
    act(() => {
      result.current.setDrawn([
        { id: 'U1', points: shown, role: 'area' },
        { id: 'U2', points: [...square], role: 'area' },
      ]);
      result.current.showDrawn(shown);
    });
    act(() => {
      result.current.setDrawn([{ id: 'U1', points: shown, role: 'area' }]);
    });
    expect(result.current.area).toHaveProperty('polygon');
  });
});

describe('the drawings of the assistant', () => {
  const shape = {
    id: 'A1',
    kind: 'point',
    label_at: [1, 1],
    position: [1, 1],
  } as unknown as DrawShape;
  const fakeMap = () => ({ draw: vi.fn(), clear: vi.fn(), show: vi.fn() }) satisfies AiMap;

  it('go to the map when it is there', () => {
    const { result } = setup();
    const map = fakeMap();
    act(() => {
      result.current.bindAi(map);
    });
    act(() => {
      result.current.drawAi([shape], true);
      result.current.showShape('A1');
    });
    expect(map.draw).toHaveBeenCalledWith([shape], true);
    expect(map.show).toHaveBeenCalledWith('A1');
  });

  it('wait for the map when they come first, and are drawn in the order they came', () => {
    const { result } = setup();
    const map = fakeMap();
    const order: string[] = [];
    map.draw.mockImplementation((_shapes: readonly DrawShape[], replace: boolean) => {
      order.push(replace ? 'replace' : 'add');
    });
    act(() => {
      result.current.drawAi([shape], true);
      result.current.drawAi([shape], false);
    });
    expect(map.draw).not.toHaveBeenCalled();
    act(() => {
      result.current.bindAi(map);
    });
    expect(order).toEqual(['replace', 'add']);
  });

  it('that are cleared before the map is there are not drawn at all', () => {
    const { result } = setup();
    const map = fakeMap();
    act(() => {
      result.current.drawAi([shape], false);
      result.current.clearAi();
      result.current.bindAi(map);
    });
    expect(map.draw).not.toHaveBeenCalled();
  });
});
