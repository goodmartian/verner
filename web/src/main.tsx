import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import '@fontsource-variable/inter';
import '@fontsource/inter-tight/400.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import './styles/tokens.css';
import 'maplibre-gl/dist/maplibre-gl.css';
import './styles/app.css';
import './styles/overrides.css';

// an answer is fresh for half a minute: a tab or a dialog that asks again at once reads it from the cache, and the
// queries that know better (a day, forever) say so themselves
const client = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } });
const root = document.getElementById('root');
if (!root) throw new Error('index.html has no #root');

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
