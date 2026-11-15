import { lazy, memo, Suspense, useEffect, type ReactNode } from 'react';
import { useI18n } from '../../i18n/context';
import { useBoard } from '../board/context';
import { useFires } from '../fires/queries';
import { useWidgetActions } from './actions';
import { keepTarget, parseTarget } from './links';
import { settle, splitBlocks } from './settle';
import { useSmoothText } from './useSmoothText';

// the parser comes with the first answer, not with the first screen
const ReactMarkdown = lazy(() => import('react-markdown'));

// what an answer may be made of: paragraphs, bold, italics, lists, code, line breaks and links; nothing else, no HTML
const ALLOWED = ['p', 'strong', 'em', 'ul', 'ol', 'li', 'code', 'br', 'a'];

function Link({ href, children }: { href?: string; children?: ReactNode }) {
  const target = href ? parseTarget(href) : null;
  // an address that is not to be followed is dropped with its link: the words stay
  if (!target) return <>{children}</>;
  if (target.kind === 'web') {
    return (
      <a href={target.url} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  }
  if (target.kind === 'fire') return <FireLink id={target.id}>{children}</FireLink>;
  if (target.kind === 'period') {
    return (
      <PeriodLink from={target.from} to={target.to}>
        {children}
      </PeriodLink>
    );
  }
  if (target.kind === 'shape') return <ShapeLink id={target.id}>{children}</ShapeLink>;
  return <AreaLink id={target.id}>{children}</AreaLink>;
}

/** A mention in an answer that does something on the board, set like the words of a link but a button: nothing opens apart. */
function Action({
  children,
  onPress,
  onHover,
}: {
  children: ReactNode;
  onPress: () => void;
  onHover?: (on: boolean) => void;
}) {
  return (
    <button
      type="button"
      className="md-link"
      onClick={onPress}
      onMouseEnter={() => onHover?.(true)}
      onMouseLeave={() => onHover?.(false)}
      onFocus={() => onHover?.(true)}
      onBlur={() => onHover?.(false)}
    >
      {children}
    </button>
  );
}

function FireLink({ id, children }: { id: string; children?: ReactNode }) {
  const { t } = useI18n();
  const actions = useWidgetActions();
  const live = useFires(false).data;
  if (!actions) return <>{children}</>;
  // a fire that is gone from the live data is words with a note, not a way to a fire that cannot be opened
  if (live?.available && !live.fires.some((fire) => fire.id === id)) {
    return (
      <span className="md-gone" title={t('link.fireGone')}>
        {children}
      </span>
    );
  }
  return (
    <Action
      onPress={() => {
        actions.openFire(id);
      }}
      onHover={(on) => {
        actions.hoverFire(on ? id : null);
      }}
    >
      {children}
    </Action>
  );
}

function PeriodLink({ from, to, children }: { from: string; to: string; children?: ReactNode }) {
  const actions = useWidgetActions();
  const { area } = useBoard();
  if (!actions) return <>{children}</>;
  return (
    <Action
      onPress={() => {
        if (area) actions.showPeriod(area, from, to);
      }}
    >
      {children}
    </Action>
  );
}

function AreaLink({ id, children }: { id: string; children?: ReactNode }) {
  const actions = useWidgetActions();
  if (!actions) return <>{children}</>;
  return (
    <Action
      onPress={() => {
        actions.showArea(id);
      }}
    >
      {children}
    </Action>
  );
}

/** The caption of a drawing of the assistant in an answer: a press centres the map on the drawing. */
function ShapeLink({ id, children }: { id: string; children?: ReactNode }) {
  const actions = useWidgetActions();
  if (!actions) return <>{children}</>;
  return (
    <Action
      onPress={() => {
        actions.showShape(id);
      }}
    >
      {children}
    </Action>
  );
}

/** A paragraph of an answer, drawn again only when its words change. */
export const Block = memo(function Block({ text }: { text: string }) {
  return (
    <Suspense fallback={<p>{text}</p>}>
      <ReactMarkdown
        allowedElements={ALLOWED}
        unwrapDisallowed
        urlTransform={keepTarget}
        components={{ a: Link }}
      >
        {text}
      </ReactMarkdown>
    </Suspense>
  );
});

interface AnswerTextProps {
  /** Tells the message apart in `onTyping`. */
  id: number;
  text: string;
  /** More of the text may still come. */
  streaming: boolean;
  /** Told when the text starts being written and when the last of it is out, for what waits for the end of the answer. */
  onTyping: (id: number, typing: boolean) => void;
}

/** The text of an answer as it is written: let out evenly, its marks kept back until they close, finished paragraphs kept as they are. */
export function AnswerText({ id, text, streaming, onTyping }: AnswerTextProps) {
  const shown = useSmoothText(text, streaming);
  const open = streaming || shown.length < text.length;
  useEffect(() => {
    onTyping(id, open);
    return () => {
      onTyping(id, false);
    };
  }, [id, open, onTyping]);
  const blocks = splitBlocks(open ? settle(shown) : shown);
  return (
    <div className="md">
      {blocks.map((block, index) => (
        <Block key={index} text={block} />
      ))}
    </div>
  );
}
