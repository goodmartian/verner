import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderI18n } from '../../test/render';
import { MapTools } from './MapTools';

function setup(props: Partial<Parameters<typeof MapTools>[0]> = {}) {
  const handlers = {
    onBasemap: vi.fn(),
    onZoomIn: vi.fn(),
    onZoomOut: vi.fn(),
    onTool: vi.fn(),
    onShape: vi.fn(),
    onUndo: vi.fn(),
    onRedo: vi.fn(),
    onClear: vi.fn(),
  };
  renderI18n(
    <MapTools
      mode="cal"
      player={false}
      onPlayer={vi.fn()}
      basemap="map"
      tool="pan"
      shape="rectangle"
      canUndo={false}
      canRedo={false}
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

describe('MapTools', () => {
  it('marks the chosen tool and picks tools on a click', async () => {
    const { onTool } = setup({ tool: 'pencil' });
    expect(screen.getByRole('button', { name: 'Pencil' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Move map' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Move map' }));
    expect(onTool).toHaveBeenCalledWith('pan');
  });

  it('names the shape button after the shape and its key, and uses the last shape', async () => {
    const { onTool } = setup({ shape: 'circle' });
    await userEvent.click(screen.getByRole('button', { name: 'Circle, O' }));
    expect(onTool).toHaveBeenCalledWith('circle');
  });

  it('offers the shapes with their keys in a menu', async () => {
    const { onShape } = setup();
    await userEvent.click(screen.getByRole('button', { name: 'Shapes' }));
    const items = screen.getAllByRole('menuitemradio');
    expect(items.map((item) => item.querySelector('kbd')?.textContent)).toEqual([
      'R',
      'O',
      'P',
      'L',
      'A',
      'E',
      'Z',
    ]);
    expect(screen.getByRole('menuitemradio', { name: /^Rectangle/ })).toBeChecked();
    await userEvent.click(screen.getByRole('menuitemradio', { name: /^Ruler/ }));
    expect(onShape).toHaveBeenCalledWith('ruler');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('offers the tactical shapes of the plan: the approach, the escape and the safe zone', async () => {
    const { onShape } = setup();
    await userEvent.click(screen.getByRole('button', { name: 'Shapes' }));
    await userEvent.click(screen.getByRole('menuitemradio', { name: /^Approach/ }));
    expect(onShape).toHaveBeenLastCalledWith('approach');
    await userEvent.click(screen.getByRole('button', { name: 'Shapes' }));
    await userEvent.click(screen.getByRole('menuitemradio', { name: /^Escape route/ }));
    expect(onShape).toHaveBeenLastCalledWith('escape');
    await userEvent.click(screen.getByRole('button', { name: 'Shapes' }));
    await userEvent.click(screen.getByRole('menuitemradio', { name: /^Safe zone/ }));
    expect(onShape).toHaveBeenLastCalledWith('safe');
  });

  it('keeps undo and redo off until there is something to undo or redo', async () => {
    const { onUndo, onRedo } = setup({ canUndo: true });
    expect(screen.getByRole('button', { name: 'Redo' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(onUndo).toHaveBeenCalled();
    expect(onRedo).not.toHaveBeenCalled();
  });

  it('clears the drawings, zooms and picks a basemap', async () => {
    const { onClear, onZoomIn, onZoomOut, onBasemap } = setup();
    await userEvent.click(screen.getByRole('button', { name: 'Clear drawings' }));
    await userEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    await userEvent.click(screen.getByRole('button', { name: 'Zoom out' }));
    await userEvent.click(screen.getByRole('button', { name: 'Layers' }));
    await userEvent.click(screen.getByRole('button', { name: 'Satellite' }));
    expect(onClear).toHaveBeenCalled();
    expect(onZoomIn).toHaveBeenCalled();
    expect(onZoomOut).toHaveBeenCalled();
    expect(onBasemap).toHaveBeenCalledWith('sat');
  });

  it('offers the layers of the weather as cards, each on or off', async () => {
    const onToggle = vi.fn();
    setup({
      mode: 'fires',
      overlays: {
        onToggle,
        cards: [
          {
            id: 'rain',
            label: 'Precipitation',
            gradient: 'linear-gradient(135deg, #fff, #36d)',
            on: true,
          },
          {
            id: 'dryness',
            label: 'Dryness',
            gradient: 'linear-gradient(135deg, #2f8f5b, #c0272d)',
            on: false,
          },
        ],
      },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Layers' }));
    expect(screen.getByRole('button', { name: 'Precipitation' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Dryness' }));
    expect(onToggle).toHaveBeenCalledWith('dryness');
  });

  it('has no weather cards without weather', async () => {
    setup({ mode: 'fires' });
    await userEvent.click(screen.getByRole('button', { name: 'Layers' }));
    expect(screen.queryByRole('button', { name: 'Precipitation' })).not.toBeInTheDocument();
  });

  it('keeps the base map and the overlays in two sections, one base and any overlays', async () => {
    setup({
      mode: 'fires',
      overlays: {
        onToggle: vi.fn(),
        cards: [
          {
            id: 'rain',
            label: 'Precipitation',
            gradient: 'linear-gradient(135deg, #fff, #36d)',
            on: true,
          },
        ],
      },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Layers' }));
    const base = screen.getByRole('group', { name: 'Base map' });
    const overlays = screen.getByRole('group', { name: 'Overlays' });
    expect(base).toContainElement(screen.getByRole('button', { name: 'Satellite' }));
    expect(overlays).toContainElement(screen.getByRole('button', { name: 'Precipitation' }));
    expect(base).not.toContainElement(screen.getByRole('button', { name: 'Precipitation' }));
    expect(screen.getByRole('separator')).toBeInTheDocument();
  });

  it('has only the base map when nothing lies over it', async () => {
    setup({ mode: 'fires' });
    await userEvent.click(screen.getByRole('button', { name: 'Layers' }));
    expect(screen.getByRole('group', { name: 'Base map' })).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Overlays' })).not.toBeInTheDocument();
  });

  it('shows the month climate as an item that is off, with its caption, while its data is not there', async () => {
    const onToggle = vi.fn();
    setup({ mode: 'cal', overlays: { onToggle, cards: [], pending: true } });
    await userEvent.click(screen.getByRole('button', { name: 'Layers' }));
    const item = screen.getByRole('button', { name: /Climate/ });
    expect(item).toBeDisabled();
    expect(item).toHaveTextContent('data is loading');
    await userEvent.click(item);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it('says there is no data for the month, and not that it is loading, when the months have weather but not this one', async () => {
    setup({ mode: 'cal', overlays: { onToggle: vi.fn(), cards: [], empty: true } });
    await userEvent.click(screen.getByRole('button', { name: 'Layers' }));
    const item = screen.getByRole('button', { name: /Climate/ });
    expect(item).toBeDisabled();
    expect(item).toHaveTextContent('no data for this month');
    expect(item).not.toHaveTextContent('loading');
    // without a month it has, there is nothing to lead to
    expect(screen.queryByText('Last month with climate:')).not.toBeInTheDocument();
  });

  it('leads a month past the weather to the last month it has', async () => {
    const run = vi.fn();
    setup({
      mode: 'cal',
      overlays: {
        onToggle: vi.fn(),
        cards: [],
        empty: true,
        latest: { label: 'September 2026', run },
      },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Layers' }));
    expect(screen.getByText('Last month with climate:')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'September 2026' }));
    expect(run).toHaveBeenCalledOnce();
  });

  it('shows the vegetation as a tile that waits while its data comes', async () => {
    const onToggle = vi.fn();
    setup({ mode: 'fires', cover: { image: null, loading: true, on: false, onToggle } });
    await userEvent.click(screen.getByRole('button', { name: 'Layers' }));
    const waiting = screen.getByRole('button', { name: /Vegetation/ });
    expect(waiting).toBeDisabled();
    expect(waiting).toHaveTextContent('data is loading');
  });

  it('turns the vegetation on and off once its data is there', async () => {
    const onToggle = vi.fn();
    setup({
      mode: 'fires',
      cover: { image: 'data:image/png;base64,AAAA', loading: false, on: false, onToggle },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Layers' }));
    await userEvent.click(screen.getByRole('button', { name: /Vegetation/ }));
    expect(onToggle).toHaveBeenCalled();
  });
});
