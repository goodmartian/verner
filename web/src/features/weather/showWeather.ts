import type { ShowWeatherAction } from '../../api/types';
import type { WeatherLayer } from './context';

export interface WeatherView {
  /** The fire to open; null leaves the one open. */
  fireId: string | null;
  /** The layers of pictures to switch on. */
  layers: WeatherLayer[];
  /** The arrows of the wind over the whole map are asked for. */
  wind: boolean;
  /** The hour to put the player at, as the interface keeps it (`…Z`); null leaves it. */
  clock: string | null;
}

/** What the assistant's `show_weather` asks of the board, in the words of the interface. */
export function weatherView(action: ShowWeatherAction): WeatherView {
  const asked = action.layers ?? [];
  return {
    fireId: action.fire_id ?? null,
    layers: asked.filter((layer): layer is WeatherLayer => layer !== 'wind'),
    wind: asked.includes('wind'),
    clock: action.hour ? (action.hour.endsWith('Z') ? action.hour : `${action.hour}Z`) : null,
  };
}
