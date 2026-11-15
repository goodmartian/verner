import { describe, expect, it } from 'vitest';
import type { FireDetail } from '../../api/types';
import { translate } from '../../i18n/translate';
import { frontSpeed } from './text';

type Spread = NonNullable<FireDetail['spread']>;
const spread = (rate: number, source: Spread['rate_source']) =>
  ({ rate_m_per_h: rate, rate_source: source }) as Spread;

const ru: Parameters<typeof frontSpeed>[0] = (key, params) => translate('ru', key, params);

describe('the speed of the head', () => {
  it('is in metres an hour below a kilometre', () => {
    expect(frontSpeed(ru, 'ru', spread(46, 'measured'))).toEqual({
      value: '46 м/ч',
      label: 'скорость фронта',
    });
  });

  it('is in km/h with a decimal from a kilometre', () => {
    expect(frontSpeed(ru, 'ru', spread(1840, 'measured')).value).toBe('1,8 км/ч');
  });

  it('says so when it comes from the weather', () => {
    expect(frontSpeed(ru, 'ru', spread(1000, 'weather')).label).toBe('скорость фронта, по погоде');
  });

  it('is none when there is no spread', () => {
    expect(frontSpeed(ru, 'ru', null).value).toBe('0 км/ч');
  });
});
