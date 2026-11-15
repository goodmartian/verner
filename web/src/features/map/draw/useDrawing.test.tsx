import { act, renderHook } from '@testing-library/react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { I18nProvider } from '../../../i18n/I18nProvider';
import { useDrawing } from './useDrawing';

type Listener = (event: unknown) => void;

function fakeMap() {
  const listeners = new Map<string, Set<Listener>>();
  const data: unknown[] = [];
  const map = {
    addSource: vi.fn(),
    addLayer: vi.fn(),
    addImage: vi.fn(),
    hasImage: () => false,
    removeImage: vi.fn(),
    getLayer: () => undefined,
    queryRenderedFeatures: () => [],
    setFeatureState: vi.fn(),
    removeFeatureState: vi.fn(),
    removeLayer: vi.fn(),
    removeSource: vi.fn(),
    // only the person's own sketch is looked at: the assistant's sources have names of their own
    getSource: (name: string) => ({
      setData: (value: unknown) => {
        if (name === 'sketch') data.push(value);
        return Promise.resolve();
      },
    }),
    on: (type: string, listener: Listener) => {
      listeners.set(type, (listeners.get(type) ?? new Set()).add(listener));
    },
    off: (type: string, listener: Listener) => {
      listeners.get(type)?.delete(listener);
    },
    project: ([x, y]: [number, number]) => ({ x: x * 100, y: y * 100 }),
    getCanvas: () => ({ style: { cursor: '' } }),
    dragPan: { enable: vi.fn(), disable: vi.fn() },
    doubleClickZoom: { enable: vi.fn(), disable: vi.fn() },
  };
  const fire = (type: string, lng: number, lat: number) => {
    for (const listener of listeners.get(type) ?? []) {
      listener({
        lngLat: { lng, lat },
        point: { x: lng * 100, y: lat * 100 },
        preventDefault: vi.fn(),
      });
    }
  };
  return { map: map as unknown as MaplibreMap, fire, data };
}

const wrapper = ({ children }: { children: ReactNode }) => <I18nProvider>{children}</I18nProvider>;

const press = (key: string, init: KeyboardEventInit = {}) => {
  act(() => {
    document.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, ...init }));
  });
};

function setup() {
  const world = fakeMap();
  const hook = renderHook(() => useDrawing(world.map), { wrapper });
  return { ...world, hook };
}

describe('useDrawing', () => {
  it('chooses shape tools with R, O, P and L, and goes back to the hand with Escape', () => {
    const { hook } = setup();
    expect(hook.result.current.tool).toBe('pan');
    press('r');
    expect(hook.result.current.tool).toBe('rectangle');
    press('o');
    expect(hook.result.current.tool).toBe('circle');
    expect(hook.result.current.shape).toBe('circle');
    press('p');
    expect(hook.result.current.tool).toBe('polygon');
    press('l');
    expect(hook.result.current.tool).toBe('ruler');
    press('a');
    expect(hook.result.current.tool).toBe('approach');
    press('e');
    expect(hook.result.current.tool).toBe('escape');
    press('z');
    expect(hook.result.current.tool).toBe('safe');
    press('Escape');
    expect(hook.result.current.tool).toBe('pan');
    // the shape the button holds is the last one chosen
    expect(hook.result.current.shape).toBe('safe');
  });

  it('leaves the keys alone while someone types, and with a modifier held', () => {
    const { hook } = setup();
    const field = document.createElement('input');
    document.body.append(field);
    field.focus();
    press('r');
    field.remove();
    press('r', { altKey: true });
    expect(hook.result.current.tool).toBe('pan');
  });

  it('undoes and redoes with Ctrl+Z, Ctrl+Shift+Z and Ctrl+Y', () => {
    const { hook, fire } = setup();
    press('r');
    act(() => {
      fire('mousedown', 0, 0);
      fire('mousemove', 2, 1);
      fire('mouseup', 2, 1);
    });
    expect(hook.result.current.canUndo).toBe(true);
    press('z', { ctrlKey: true });
    expect(hook.result.current.canUndo).toBe(false);
    expect(hook.result.current.canRedo).toBe(true);
    press('z', { ctrlKey: true, shiftKey: true });
    expect(hook.result.current.canUndo).toBe(true);
    press('z', { metaKey: true });
    press('y', { ctrlKey: true });
    expect(hook.result.current.canUndo).toBe(true);
  });

  it('paints the drawn shapes on the map and clears them again', () => {
    const { hook, fire, data } = setup();
    press('r');
    act(() => {
      fire('mousedown', 0, 0);
      fire('mousemove', 2, 1);
      fire('mouseup', 2, 1);
    });
    expect(data.at(-1)).toMatchObject({ features: [{ geometry: { type: 'Polygon' } }] });
    act(() => {
      hook.result.current.clear();
    });
    expect(data.at(-1)).toMatchObject({ features: [] });
  });

  it('closes a polygon with Enter and cancels a drawing with Escape', () => {
    const { hook, fire } = setup();
    press('p');
    act(() => {
      fire('click', 0, 0);
      fire('click', 3, 0);
      fire('click', 3, 2);
    });
    press('Enter');
    expect(hook.result.current.canUndo).toBe(true);
    act(() => {
      fire('click', 10, 10);
    });
    press('Escape');
    expect(hook.result.current.tool).toBe('polygon');
    press('Escape');
    expect(hook.result.current.tool).toBe('pan');
  });
});
