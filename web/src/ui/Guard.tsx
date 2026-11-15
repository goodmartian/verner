import { Component, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useI18n } from '../i18n/context';
import { EmptyNote } from './EmptyNote';

interface CatchProps {
  children: ReactNode;
  fallback: (retry: () => void) => ReactNode;
}

/** Holds the failure of a block of the page inside it: the rest of the page stays as it is. */
class Catch extends Component<CatchProps, { failed: boolean }> {
  override state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  override render() {
    return this.state.failed
      ? this.props.fallback(() => {
          this.setState({ failed: false });
        })
      : this.props.children;
  }
}

/** A block that fails to draw says so with a button that tries it again, and does not take the page with it. */
export function Guard({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const client = useQueryClient();
  return (
    <Catch
      fallback={(retry) => (
        <div className="guard" role="alert">
          <EmptyNote
            wide
            icon="arrow-clockwise"
            text={t('error.block')}
            actions={[
              {
                label: t('chat.retry'),
                run: () => {
                  retry();
                  void client.invalidateQueries();
                },
              },
            ]}
          />
        </div>
      )}
    >
      {children}
    </Catch>
  );
}
