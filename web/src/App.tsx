import { BoardProvider } from './features/board/BoardProvider';
import { FiresProvider } from './features/fires/FiresProvider';
import { WeatherProvider } from './features/weather/WeatherProvider';
import { I18nProvider } from './i18n/I18nProvider';
import { Shell } from './layout/Shell';
import { ConfigProvider } from './config/ConfigProvider';

export function App() {
  return (
    <ConfigProvider>
      <I18nProvider>
        <BoardProvider>
          <FiresProvider>
            <WeatherProvider>
              <Shell />
            </WeatherProvider>
          </FiresProvider>
        </BoardProvider>
      </I18nProvider>
    </ConfigProvider>
  );
}
