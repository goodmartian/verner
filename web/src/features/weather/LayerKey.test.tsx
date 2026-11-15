import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderI18n } from '../../test/render';
import { LayerKey, tickIndexes, type KeyRow } from './LayerKey';

describe('tickIndexes', () => {
  it('writes every meeting of the bands when there are few', () => {
    expect(tickIndexes(3)).toEqual([0, 1, 2]);
    expect(tickIndexes(4)).toEqual([0, 1, 2, 3]);
  });

  it('spreads four values along a long strip, the first and the last among them', () => {
    expect(tickIndexes(5)).toEqual([0, 1, 3, 4]);
    expect(tickIndexes(8)).toEqual([0, 2, 5, 7]);
  });
});

const ROWS: KeyRow[] = [
  {
    id: 'rain',
    title: 'Precipitation',
    unit: 'mm/h',
    bands: [
      { id: 0, low: 0, color: '#fff' },
      { id: 1, low: 0.1, color: '#cfe6ff' },
    ],
  },
  {
    id: 'dryness',
    title: 'Dryness',
    unit: 'kPa',
    bands: [
      { id: 0, low: 0, color: '#2f8f5b' },
      { id: 1, low: 0.5, color: '#9acb5a' },
    ],
  },
];

describe('LayerKey', () => {
  it('has a strip for each layer, with its unit and the value where the bands meet', () => {
    renderI18n(<LayerKey rows={ROWS} />);
    expect(screen.getByRole('heading', { name: /Precipitation mm\/h/ })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Dryness kPa/ })).toBeInTheDocument();
    expect(screen.getByText('0.1')).toBeInTheDocument();
    expect(screen.getByText('0.5')).toBeInTheDocument();
  });

  it('says what is missing instead of the strips', () => {
    renderI18n(<LayerKey rows={ROWS.slice(0, 1)} missing="No data for this hour" />);
    expect(screen.getByText('No data for this hour')).toBeInTheDocument();
    expect(screen.queryByText('0.1')).not.toBeInTheDocument();
  });

  it('has dots with names for the vegetation', () => {
    renderI18n(
      <LayerKey
        rows={[]}
        cover={[
          { id: 1, name: 'Grass', color: '#aab' },
          { id: 2, name: 'Forest', color: '#161' },
        ]}
      />,
    );
    expect(screen.getByRole('heading', { name: 'Vegetation' })).toBeInTheDocument();
    expect(screen.getByText('Grass')).toBeInTheDocument();
    expect(screen.getByText('Forest')).toBeInTheDocument();
  });

  it('draws nothing when there is nothing to key', () => {
    const { container } = renderI18n(<LayerKey rows={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
