import { useQuery } from '@tanstack/react-query';
import { useMemo, type ReactNode } from 'react';
import { ConfigContext } from './context';
import { ConfigError } from './ConfigError';
import { loadConfig, mergeRegions } from './load';
import { useRegions } from '../features/calendar/queries';

export function ConfigProvider({ children }: { children: ReactNode }) {
  const { data, isError, refetch } = useQuery({
    queryKey: ['config'],
    queryFn: loadConfig,
    staleTime: Infinity,
    retry: false,
  });
  const regions = useRegions().data;
  const value = useMemo(
    () => (data ? mergeRegions(data, regions?.regions ?? [], regions?.types) : null),
    [data, regions],
  );
  if (isError) {
    return (
      <ConfigError
        onRetry={() => {
          void refetch();
        }}
      />
    );
  }
  return <ConfigContext value={value}>{children}</ConfigContext>;
}
