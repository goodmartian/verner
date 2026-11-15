import { describe, expect, it } from 'vitest';
import { translate } from '../../i18n/translate';
import { unitText } from './units';

const ru = (key: Parameters<typeof translate>[1]) => translate('ru', key);

describe('unitText', () => {
  it('writes the units of the server in Russian', () => {
    expect(unitText(ru, 'km/h')).toBe('км/ч');
    expect(unitText(ru, 'mm/h')).toBe('мм/ч');
    expect(unitText(ru, 'kPa')).toBe('кПа');
  });
  it('leaves a unit it does not know as it came', () => {
    expect(unitText(ru, '°C')).toBe('°C');
  });
});
