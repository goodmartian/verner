import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { BoardProvider } from '../features/board/BoardProvider';
import { FiresProvider } from '../features/fires/FiresProvider';
import { WeatherProvider } from '../features/weather/WeatherProvider';
import { I18nProvider } from '../i18n/I18nProvider';
import { ConfigContext } from '../config/context';
import { makeConfig } from './configFixtures';
import type { AppConfig } from '../config/types';

/** Renders with everything the app wraps its screens in. */
export function renderApp(ui: ReactElement, config: AppConfig | null = makeConfig()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConfigContext value={config}>
        <I18nProvider>
          <BoardProvider>
            <FiresProvider>
              <WeatherProvider>{ui}</WeatherProvider>
            </FiresProvider>
          </BoardProvider>
        </I18nProvider>
      </ConfigContext>
    </QueryClientProvider>,
  );
}

/** Renders with translations only, for parts that do not talk to the server. */
export function renderI18n(ui: ReactElement, config: AppConfig = makeConfig()) {
  return render(
    <ConfigContext value={config}>
      <I18nProvider>{ui}</I18nProvider>
    </ConfigContext>,
  );
}
