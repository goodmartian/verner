import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { api, ApiError, call } from '../../api/client';
import { useApiErrorText } from '../../api/useApiErrorText';
import { useI18n } from '../../i18n/context';
import type { MessageKey } from '../../i18n/en';
import { formatLocalTime } from '../../lib/time';
import { placeZone, usePlaceZone } from '../../config/usePlaceZone';
import { useFiresState } from '../fires/context';
import { PlanDock } from '../fires/PlanDock';
import { planCopy } from '../fires/planText';
import { PlanAnswer, PlanAsk, PlanChips, PlanFields } from '../fires/PlanTurn';
import { formatWhen } from '../../lib/format';
import { Ph, type PhName } from '../../ui/Ph';
import { PopupMenu } from '../../ui/PopupMenu';
import { AgentSteps } from './AgentSteps';
import type { Attachment } from './attachments';
import { AnswerText } from './Markdown';
import { useStickToBottom } from './useStickToBottom';
import { CHATS_KEY, RETRYABLE, type ChatMessage } from './useChat';
import { WidgetView } from './WidgetView';

export type ChatVariant = 'bar' | 'panel';

export interface Addable {
  key: string;
  icon: PhName;
  label: string;
  onPick: () => void;
}

export interface Suggestion {
  text: string;
  icon: PhName;
}

const KNOWN_STEPS = new Set([
  'area_calendar',
  'list_regions',
  'period_stats',
  'forecast',
  'provinces',
  'month_detail',
  'countries',
  'area_stats',
  'live_fires',
  'fire_detail',
  'build_plan',
  'draw_on_map',
  'fire_weather',
  'weather_in_area',
  'place_weather',
  'month_weather',
]);

const stepKey = (tool: string): MessageKey =>
  tool === 'provinces'
    ? 'chat.step.regions'
    : KNOWN_STEPS.has(tool)
      ? (`chat.step.${tool}` as MessageKey)
      : 'chat.step.default';

interface AiPanelProps {
  variant: ChatVariant;
  onVariant: (variant: ChatVariant) => void;
  /** Opens the settings menu from the button given: the assistant has a gear of its own on a narrow screen. */
  onSettings: (button: HTMLElement) => void;
  /** Hands the panel's element to the page, which frames the map around it. */
  rootRef: (element: HTMLElement | null) => void;
  wide: boolean;
  onWide: () => void;
  messages: readonly ChatMessage[];
  busy: boolean;
  /** Stops the answer that is coming; what has come stays. */
  onStop?: () => void;
  onSend: (text: string, attachments: readonly Attachment[]) => void;
  /** Asks the question of an answer that failed again. */
  onRetry: (answerId: number) => void;
  onOpenChat: (id: string) => void;
  onDeleteChat: (id: string) => void;
  onNewChat: () => void;
  attachments: readonly Attachment[];
  onAttachments: (next: readonly Attachment[]) => void;
  /** The plan window takes the place of the conversation. */
  dockOpen: boolean;
  /** A fire is open: the plan form can be turned on. */
  canPlan: boolean;
  /** Makes the plan of the open fire from the form; the note is what the operator wrote with it. */
  onPlan: (note: string) => void;
  /** What the "+" can put on the question: the month on the map, the areas drawn. */
  addable: readonly Addable[];
  suggestions: readonly Suggestion[];
  /** Changes when the field should take the cursor, after something was attached. */
  focusKey: number;
  foot: RefObject<HTMLDivElement | null>;
}

function Chip({ item, onRemove }: { item: Attachment; onRemove?: () => void }) {
  const { t } = useI18n();
  const remove = onRemove ? (
    <button type="button" className="icon-btn" aria-label={t('att.remove')} onClick={onRemove}>
      <Ph name="x" />
    </button>
  ) : null;
  if (item.kind === 'area') {
    // a drawing of the assistant is known by its caption, the person's area by its number
    const name = item.label ?? t('att.area', { n: item.n });
    return (
      <span className="att att-area" title={name}>
        <Ph name={item.label ? 'sparkle' : item.role === 'safe_zone' ? 'shield' : 'polygon'} />
        <span aria-label={name}>{item.label ?? item.n}</span>
        {remove}
      </span>
    );
  }
  if (item.kind === 'fact') {
    const text = `${item.label}: ${item.value}`;
    return (
      <span className="att" title={`${text} (${item.area}, ${item.period})`}>
        <Ph name="chart-bar" />
        <span>{text}</span>
        {remove}
      </span>
    );
  }
  return (
    <span className="att" title={item.label}>
      <Ph name="calendar-dots" />
      <span>{item.label}</span>
      {remove}
    </span>
  );
}

function CopyButton({ text }: { text: string }) {
  const { t } = useI18n();
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="icon-btn copy-a"
      aria-label={t('chat.copy')}
      onClick={() => {
        void navigator.clipboard
          .writeText(text)
          .then(() => {
            setDone(true);
            window.setTimeout(() => {
              setDone(false);
            }, 1500);
          })
          .catch(() => undefined);
      }}
    >
      <Ph name={done ? 'check' : 'copy'} />
    </button>
  );
}

/** The assistant: a line at the bottom, or the panel with the conversation; history, a new chat and the plus sit in the line of the field, the way to widen and fold it in the head. */
export function AiPanel({
  variant,
  onVariant,
  onSettings,
  rootRef,
  wide,
  onWide,
  messages,
  busy,
  onStop,
  onSend,
  onRetry,
  onOpenChat,
  onDeleteChat,
  onNewChat,
  attachments,
  onAttachments,
  canPlan,
  onPlan,
  dockOpen,
  addable,
  suggestions,
  focusKey,
  foot,
}: AiPanelProps) {
  const { t, lang, locale } = useI18n();
  const errorText = useApiErrorText();
  const fires = useFiresState();
  const planning = fires.planning && canPlan;
  const [text, setText] = useState('');
  const [history, setHistory] = useState(false);
  const [adding, setAdding] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const anchor = useRef<HTMLElement | null>(null);
  const thread = useRef<HTMLDivElement>(null);
  const chats = useQuery({
    enabled: history,
    queryKey: CHATS_KEY,
    queryFn: () => call(api.GET('/api/chats')),
  });
  const zone = usePlaceZone();
  // an area without its own clock has no time to show: nothing stands in its place, and no guess of the browser's zone
  const clock = (message: ChatMessage) => {
    const text = formatLocalTime(locale, message.at, placeZone(message.work?.fire, zone));
    return text ? <time>{text}</time> : null;
  };
  const ready = !busy && (planning || text.trim() !== '' || attachments.length > 0);

  useEffect(() => {
    const element = field.current;
    if (!element) return;
    // an empty field is one line, and the stylesheet sizes it for the view it is in: a height measured here would
    // outlive the view it was measured in (the panel's taller field, a wider placeholder) and stand under the layout
    element.style.height = '';
    if (text === '') return;
    element.style.height = 'auto';
    // the stylesheet's max-height caps it: a short limit in the panel, a share of the window in the folded line
    element.style.height = `${String(element.scrollHeight)}px`;
  }, [text, attachments.length, variant]);

  useEffect(() => {
    if (focusKey > 0) field.current?.focus();
  }, [focusKey]);

  // the thread follows the answer while the person is at its bottom, and lets go when they scroll up
  const { atBottom, toBottom } = useStickToBottom(thread, messages.length);
  // the answers still being written out: what waits for the end of an answer waits for this too, or it would be pushed down
  const [typing, setTyping] = useState<ReadonlySet<number>>(new Set());
  const onTyping = useCallback((id: number, on: boolean) => {
    setTyping((now) => {
      if (now.has(id) === on) return now;
      const next = new Set(now);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  const send = (question: string) => {
    if (planning) {
      onPlan(question);
      setText('');
      return;
    }
    onVariant('panel');
    onSend(question, attachments);
    setText('');
    onAttachments([]);
  };
  const asked = new Set(messages.filter((m) => m.role === 'user').map((m) => m.text));
  // after a plan the card of the plan is the next step, not a general question
  const more = messages.at(-1)?.work ? [] : suggestions.filter((item) => !asked.has(item.text));
  const suggestionButtons = (list: readonly Suggestion[]) =>
    list.map((item) => (
      <button
        key={item.text}
        type="button"
        className="sugg-btn"
        disabled={busy}
        onClick={() => {
          send(item.text);
        }}
      >
        <Ph name={item.icon} />
        <span>{item.text}</span>
      </button>
    ));
  const openHistory = (button: HTMLElement) => {
    anchor.current = button;
    setAdding(false);
    setHistory((now) => !now);
  };
  const openAdd = (button: HTMLElement) => {
    anchor.current = button;
    setHistory(false);
    setAdding((now) => !now);
  };

  return (
    <aside ref={rootRef} className="panel ai" aria-labelledby="h-ai">
      <div className="ai-card">
        <header className="ai-head">
          <h2 id="h-ai">{t('chat.title')}</h2>
          <button
            type="button"
            className="icon-btn"
            id="settings-btn-f"
            aria-haspopup="menu"
            aria-label={t('settings.title')}
            onClick={(event) => {
              onSettings(event.currentTarget);
            }}
          >
            <Ph name="gear-six" />
          </button>
          <button
            type="button"
            className="icon-btn"
            id="hist-btn"
            aria-expanded={history}
            aria-haspopup="menu"
            aria-label={t('chat.history')}
            onClick={(event) => {
              openHistory(event.currentTarget);
            }}
          >
            <Ph name="clock-counter-clockwise" />
          </button>
          <button
            type="button"
            className="icon-btn"
            id="new-chat"
            aria-label={t('chat.new')}
            onClick={onNewChat}
          >
            <Ph name="pencil-simple" />
          </button>
          <button
            type="button"
            className="icon-btn"
            id="ai-max"
            aria-expanded={wide}
            aria-label={t(wide ? 'common.shrink' : 'common.expand')}
            onClick={onWide}
          >
            <Ph name={wide ? 'arrows-in-line-horizontal' : 'arrows-out-line-horizontal'} />
          </button>
          <button
            type="button"
            className="icon-btn chat-min"
            id="chat-min"
            aria-label={t('chat.minimize')}
            onClick={() => {
              onVariant('bar');
            }}
          >
            <Ph name="caret-down" />
          </button>
        </header>
        <div
          className="thread"
          id="thread"
          aria-live="polite"
          aria-busy={busy || typing.size > 0}
          ref={thread}
        >
          {messages.length === 0 ? (
            <div className="empty">
              <h3>{t('chat.hello')}</h3>
              <div className="sugg">{suggestionButtons(suggestions)}</div>
            </div>
          ) : (
            messages.map((message) =>
              message.role === 'user' ? (
                <div key={message.id} className="msg q">
                  <div className="bubble">
                    {message.attachments.length > 0 ? (
                      <div className="atts">
                        {message.attachments.map((item, index) => (
                          <Chip key={index} item={item} />
                        ))}
                      </div>
                    ) : null}
                    <p>
                      <span className="visually-hidden">{t('chat.you')}: </span>
                      {message.text}
                    </p>
                    {message.work ? <PlanAsk turn={message.work} /> : null}
                  </div>
                  {clock(message)}
                </div>
              ) : (
                <div key={message.id} className="msg a">
                  <div className="body">
                    {message.work ? (
                      <PlanAnswer
                        turn={message.work}
                        status={message.status}
                        startedAt={message.at}
                        onOpen={() => {
                          fires.setDock(true);
                        }}
                      />
                    ) : null}
                    {message.work ? null : message.steps.length > 0 ? (
                      <AgentSteps
                        steps={message.steps.map((tool, index) => ({
                          id: `${String(index)}-${tool}`,
                          label: t(stepKey(tool)),
                          status:
                            index === message.steps.length - 1 && message.status === 'streaming'
                              ? 'running'
                              : 'done',
                        }))}
                        folded={message.status !== 'streaming' || message.text !== ''}
                      />
                    ) : message.status === 'streaming' && !message.text ? (
                      <p className="think-line" role="status">
                        <span className="shimmer think">{t('chat.thinking')}…</span>
                      </p>
                    ) : null}
                    {message.text ? (
                      <AnswerText
                        id={message.id}
                        text={message.text}
                        streaming={message.status === 'streaming'}
                        onTyping={onTyping}
                      />
                    ) : null}
                    {/* the cards of an answer come after its words: they wait until the last word is written */}
                    {message.status === 'streaming' || typing.has(message.id)
                      ? null
                      : message.widgets.map((widget, index) => (
                          <WidgetView key={index} widget={widget} order={index} />
                        ))}
                    {message.status === 'error' ? (
                      <div
                        className={message.errorCode === 'plan_unavailable' ? 'note' : 'msg-error'}
                        role={message.errorCode === 'plan_unavailable' ? 'status' : 'alert'}
                      >
                        <p>
                          {errorText(
                            new ApiError(
                              0,
                              message.errorCode ?? 'network',
                              '',
                              [],
                              message.retryAfter ?? null,
                            ),
                          )}
                        </p>
                        {RETRYABLE.has(message.errorCode ?? 'network') ? (
                          <button
                            type="button"
                            className="btn btn-secondary"
                            onClick={() => {
                              onRetry(message.id);
                            }}
                          >
                            {t('chat.retry')}
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                  {message.status === 'streaming' ? null : (
                    <div className="meta">
                      {clock(message)}
                      <CopyButton
                        text={
                          message.work?.plan
                            ? planCopy(t, lang, message.work.plan, message.work.fire, zone)
                            : message.text
                        }
                      />
                    </div>
                  )}
                </div>
              ),
            )
          )}
          {messages.length > 0 && !busy && typing.size === 0 && more.length > 0 ? (
            <div className="sugg row" id="sugg">
              {suggestionButtons(more)}
            </div>
          ) : null}
        </div>
        {messages.length > 0 && !atBottom ? (
          <button
            type="button"
            className="icon-btn to-bottom"
            aria-label={t('chat.toBottom')}
            onClick={toBottom}
          >
            <Ph name="arrow-down" />
          </button>
        ) : null}
        {dockOpen ? (
          <PlanDock
            wide={wide}
            onWide={onWide}
            onClose={() => {
              fires.setDock(false);
            }}
          />
        ) : null}
      </div>
      <div className="ai-foot" ref={foot}>
        <form
          className={`composer${busy ? ' busy' : ''}`}
          id="ask-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (ready) send(text.trim());
          }}
        >
          <div className="c-box">
            <span className="busy-fx fx-glow" aria-hidden="true">
              <i />
            </span>
            <span className="busy-fx fx-ring" aria-hidden="true">
              <i />
            </span>
            {planning ? <PlanChips /> : null}
            <div className="atts" id="atts">
              {attachments.map((item, index) => (
                <Chip
                  key={index}
                  item={item}
                  onRemove={() => {
                    onAttachments(attachments.filter((_, i) => i !== index));
                  }}
                />
              ))}
            </div>
            <label htmlFor="q" className="visually-hidden">
              {t('chat.placeholder')}
            </label>
            <textarea
              ref={field}
              id="q"
              rows={1}
              value={text}
              autoComplete="off"
              placeholder={
                planning ? t('pl.notePh') : busy ? `${t('chat.thinking')}…` : t('chat.placeholder')
              }
              onChange={(event) => {
                setText(event.target.value);
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  if (ready) send(text.trim());
                }
              }}
            />
            <div className="c-row">
              <div className="c-left">
                <button
                  type="button"
                  className="icon-btn chat-open"
                  id="chat-open"
                  aria-label={t('chat.open')}
                  onClick={() => {
                    onVariant('panel');
                  }}
                >
                  <Ph name="caret-up" />
                </button>
                <button
                  type="button"
                  className="icon-btn"
                  id="plus-btn"
                  aria-expanded={adding}
                  aria-haspopup="menu"
                  aria-label={t('chat.add')}
                  onClick={(event) => {
                    openAdd(event.currentTarget);
                  }}
                >
                  <Ph name="plus" />
                </button>
              </div>
              {planning ? <PlanFields /> : null}
              {busy && onStop ? (
                <button
                  type="button"
                  className="send"
                  id="send"
                  aria-label={t('chat.stop')}
                  onClick={onStop}
                >
                  <Ph name="stop" fill />
                </button>
              ) : (
                <button
                  type="submit"
                  className="send"
                  id="send"
                  aria-label={t('chat.send')}
                  disabled={!ready}
                >
                  <Ph name="arrow-up" />
                </button>
              )}
            </div>
          </div>
        </form>
      </div>
      <PopupMenu
        anchor={anchor}
        open={adding}
        className="plus-menu"
        label={t('chat.add')}
        id="plus-menu"
        up
        onClose={() => {
          setAdding(false);
        }}
      >
        {addable.length === 0 && !canPlan ? (
          <p className="menu-label">{t('chat.addEmpty')}</p>
        ) : null}
        {canPlan ? (
          <button
            type="button"
            className="menu-item"
            role="menuitemcheckbox"
            id="plan-pill"
            aria-checked={planning}
            onClick={() => {
              setAdding(false);
              fires.setPlanning(!planning);
              if (!planning) field.current?.focus();
            }}
          >
            <span className="mi">
              <Ph name="path" />
              <span>{t('plan.title')}</span>
            </span>
            <Ph name="check" />
          </button>
        ) : null}
        {addable.map((item) => (
          <button
            key={item.key}
            type="button"
            className="menu-item"
            role="menuitem"
            onClick={() => {
              setAdding(false);
              item.onPick();
            }}
          >
            <span className="mi">
              <Ph name={item.icon} />
              <span>{item.label}</span>
            </span>
          </button>
        ))}
      </PopupMenu>
      <PopupMenu
        anchor={anchor}
        open={history}
        className="hist-menu"
        label={t('chat.history')}
        id="hist-menu"
        align="end"
        onClose={() => {
          setHistory(false);
          setConfirming(null);
        }}
      >
        <div className="menu-label">{t('chat.history')}</div>
        {chats.data?.length === 0 ? <p className="menu-label">{t('chat.historyEmpty')}</p> : null}
        {chats.data?.map((chat) => (
          <div key={chat.id} className="hist-row">
            <button
              type="button"
              className="menu-item hist-item"
              role="menuitem"
              onClick={() => {
                setHistory(false);
                onOpenChat(chat.id);
              }}
            >
              <span>
                <b>{chat.title || t('chat.untitled')}</b>
                <small>{formatWhen(lang, chat.updated_at, zone)}</small>
              </span>
            </button>
            {confirming === chat.id ? (
              <button
                type="button"
                className="btn btn-secondary"
                role="menuitem"
                onClick={() => {
                  setConfirming(null);
                  onDeleteChat(chat.id);
                }}
              >
                {t('chat.delete')}
              </button>
            ) : (
              <button
                type="button"
                className="icon-btn"
                role="menuitem"
                aria-label={`${t('chat.deleteChat')}: ${chat.title || t('chat.untitled')}`}
                onClick={() => {
                  setConfirming(chat.id);
                }}
              >
                <Ph name="trash" />
              </button>
            )}
          </div>
        ))}
      </PopupMenu>
    </aside>
  );
}
