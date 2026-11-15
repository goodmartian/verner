import { useEffect, useState } from 'react';

const SHOWN_MS = 4000;

/**
 * A short notice over the map that goes by itself. It shows once when a message comes (from nothing to a text) and not again while
 * the same state goes on; when the message is gone, the next one shows anew.
 */
export function Toast({ message }: { message: string | null }) {
  const has = message !== null;
  const [expired, setExpired] = useState(false);
  const [seen, setSeen] = useState(has);
  // a new coming of a message starts the count anew
  if (seen !== has) {
    setSeen(has);
    setExpired(false);
  }

  useEffect(() => {
    if (!has) return;
    const timer = window.setTimeout(() => {
      setExpired(true);
    }, SHOWN_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [has]);

  const visible = has && !expired;
  return (
    <div className="toast" role="status" data-shown={visible ? 'on' : undefined}>
      {visible ? message : null}
    </div>
  );
}
