import type { CountryItem } from '../features/region/RegionDialog';
const name = (en: string, ru = en, es = en) => ({ en, ru, es });

export const COUNTRIES: CountryItem[] = [
  {
    id: 'AR',
    names: name('Argentina', 'Аргентина'),
    provinces: [
      { id: 'AR-W', names: name('Corrientes') },
      { id: 'AR-X', names: name('Córdoba') },
      { id: 'AR-A', names: name('Salta') },
    ],
  },
  { id: 'BR', names: name('Brazil', 'Бразилия', 'Brasil') },
  { id: 'CL', names: name('Chile', 'Чили') },
];
