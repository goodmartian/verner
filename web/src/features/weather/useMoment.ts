import { useEffect, useState } from 'react';
import { useFiresState } from '../fires/context';
import { useFiresList } from '../fires/queries';
import { thisHour, weatherMoment } from './time';

/** The present hour, kept up to date. */
export function useNowHour(): string {
  const [now, setNow] = useState(() => thisHour(Date.now()));
  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(thisHour(Date.now()));
    }, 60_000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);
  return now;
}

/** The hour the weather on the map and in the card is for: that of the player while it is open, else the present one. */
export function useWeatherMoment(): string {
  const { player, clock, pass, forecast } = useFiresState();
  const passes = useFiresList().data?.passes;
  const now = useNowHour();
  const here = passes?.[pass ?? passes.length - 1];
  return weatherMoment({ player, clock, pass: here?.time ?? null, forecast, now });
}
