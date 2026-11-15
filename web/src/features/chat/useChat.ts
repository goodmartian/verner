import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, call, callEmpty } from '../../api/client';
import type { Action, ChatEvent, FireDetail, FirePlan, Widget } from '../../api/types';
import { useBoard } from '../board/context';
import { useFiresState } from '../fires/context';
import { thin } from '../map/draw/geometry';
import { useRange } from '../calendar/queries';
import type { Attachment } from './attachments';
import { askChat } from './stream';
import { monthAttachment } from '../../api/area';
import { areaId } from '../../config/context';

export const CHATS_KEY = ['chats'] as const;

/** A work plan asked for in the conversation: what was asked, and the plan once it is made. */
/** How long the answer may be silent, in milliseconds, before it counts as lost. */
export const SILENCE_MS = 60_000;

/** The `errorCode`s of an answer that was cut short: the question can be asked again. */
export const RETRYABLE = new Set(['interrupted', 'silence', 'network']);

export interface PlanTurn {
  fire: FireDetail;
  crews: number;
  hours: number;
  /** Marks near the fire: entries and hotspots. */
  entries: number;
  hots: number;
  area: boolean;
  plan: FirePlan | null;
  /** How long the planner took. */
  seconds: number;
}

export interface ChatMessage {
  id: number;
  role: 'user' | 'assistant';
  text: string;
  /** The tools the assistant is reading from, in the order it called them. */
  steps: string[];
  widgets: Widget[];
  actions: Action[];
  status: 'streaming' | 'done' | 'error';
  /** When the message was made. */
  at: number;
  /** What the person attached to a question. */
  attachments: readonly Attachment[];
  /** The `code` of the error that ended the answer. */
  errorCode?: string;
  /** Seconds the server asked to wait before the next question, when it refused one. */
  retryAfter?: number | null;
  /** Set on the two messages of a plan made from the plan form. */
  work?: PlanTurn;
}

function apply(message: ChatMessage, event: ChatEvent): ChatMessage {
  switch (event.event) {
    case 'start':
      return message;
    case 'step':
      return { ...message, steps: [...message.steps, event.data.tool] };
    case 'text':
      return { ...message, text: message.text + event.data.text };
    case 'widget':
      return { ...message, widgets: [...message.widgets, event.data] };
    case 'action':
      return { ...message, actions: [...message.actions, event.data] };
    case 'done':
      return { ...message, status: 'done' };
    case 'error':
      return { ...message, status: 'error', errorCode: event.data.code };
  }
}

const isEmpty = (m: ChatMessage) =>
  m.text === '' && m.widgets.length === 0 && m.actions.length === 0;

/** What the person has open, beside the board: the tab, the name of the area and the month on the map. */
export interface ChatContext {
  tab: string | null;
  areaName: string | null;
  month: string | null;
}

/** One conversation: the questions asked and the answers as they stream in. */
export function useChat(onAction: (action: Action) => void, onPlan?: (plan: FirePlan) => void) {
  const client = useQueryClient();
  const board = useBoard();
  const { fireId } = useFiresState();
  const { drawn, drawAi, clearAi } = board;
  const { range } = useRange();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const chatId = useRef('new');
  const next = useRef(1);
  const abort = useRef<AbortController | null>(null);
  // the person pressed Stop: what has come stays as the answer, with no error
  const stopped = useRef(false);
  const wasStopped = () => stopped.current;

  useEffect(
    () => () => {
      abort.current?.abort();
    },
    [],
  );

  const send = useCallback(
    async (
      text: string,
      attachments: readonly Attachment[] = [],
      context: ChatContext = { tab: null, areaName: null, month: null },
    ) => {
      const questionId = next.current;
      const answerId = questionId + 1;
      const update = (change: (message: ChatMessage) => ChatMessage) => {
        setMessages((all) => all.map((m) => (m.id === answerId ? change(m) : m)));
      };
      const blank = { text: '', steps: [], widgets: [], actions: [], at: Date.now() };
      // a stopped answer stays as far as it came; one that had said nothing goes, and the question stays
      const settle = () => {
        setMessages((all) =>
          all.flatMap((m) =>
            m.id !== answerId ? [m] : isEmpty(m) ? [] : [{ ...m, status: 'done' as const }],
          ),
        );
      };
      setMessages((all) => [
        ...all,
        { id: questionId, role: 'user', ...blank, attachments, text, status: 'done' },
        { id: answerId, role: 'assistant', ...blank, attachments: [], status: 'streaming' },
      ]);
      next.current += 2;
      const controller = new AbortController();
      abort.current = controller;
      stopped.current = false;
      // an answer that says nothing for a minute is given up: the request is cancelled, and the person told
      const watch = { silent: false };
      let timer = 0;
      const listen = () => {
        window.clearTimeout(timer);
        timer = window.setTimeout(() => {
          watch.silent = true;
          controller.abort();
        }, SILENCE_MS);
      };
      try {
        // a figure of the board goes as a line of the board: `label: value (area, period)`
        const facts = attachments.flatMap((item) =>
          item.kind === 'fact'
            ? [`${item.label}: ${item.value} (${item.area}, ${item.period})`]
            : [],
        );
        const sent = attachments.filter((item) => item.kind !== 'fact');
        // what is drawn on the map goes by name (`U1`): the assistant asks the service for an area by its name.
        // The area the calendar shows is one of them; one that is not on the map (a saved area) goes as `board`.
        const shown = board.polygon
          ? (drawn.find((area) => area.points === board.polygon)?.id ?? 'board')
          : null;
        const areas = [
          ...(shown === 'board' && board.polygon
            ? [{ id: 'board', polygon: thin(board.polygon), role: 'area' as const }]
            : []),
          ...drawn.map((area) => ({ id: area.id, polygon: thin(area.points), role: area.role })),
        ].slice(0, 10);
        const question = {
          // the text is what the person asked and nothing else: the service tells the model what the board shows
          text,
          attachments: sent.map((item) =>
            item.kind === 'month'
              ? monthAttachment(item)
              : {
                  kind: 'area' as const,
                  id: item.id,
                  polygon: thin(item.points),
                  role: item.role ?? ('area' as const),
                },
          ),
          board: {
            tab: context.tab,
            area: areaId(board.area),
            area_name: context.areaName,
            first_month: range?.from ?? null,
            last_month: range?.to ?? null,
            month: context.month,
            fire_id: fireId,
            facts: facts.slice(0, 10),
            areas,
            drawn_area: shown,
          },
        };
        // a chat that this question made is deleted by the service when the answer fails
        const fresh = chatId.current === 'new';
        let finished = false;
        listen();
        for await (const event of askChat(chatId.current, question, controller.signal)) {
          listen();
          // the chat has its id from the first event: a question after a stopped answer goes on in the same chat
          if (event.event === 'start' || event.event === 'done')
            chatId.current = event.data.chat_id;
          if (event.event === 'done' || event.event === 'error') finished = true;
          if (event.event === 'error' && fresh) chatId.current = 'new';
          if (event.event === 'action') onAction(event.data);
          // a plan the assistant makes now goes on the map; a chat opened from the history does not move it
          if (event.event === 'widget' && event.data.type === 'work_plan')
            onPlan?.(event.data.data);
          update((message) => apply(message, event));
        }
        // the connection closed without `done` or `error`: the answer was cut off
        if (wasStopped()) {
          settle();
        } else if (watch.silent || !finished) {
          update((message) =>
            message.status === 'streaming'
              ? { ...message, status: 'error', errorCode: watch.silent ? 'silence' : 'interrupted' }
              : message,
          );
        }
      } catch (error) {
        if (wasStopped()) settle();
        else
          update((message) => ({
            ...message,
            status: 'error',
            errorCode: watch.silent
              ? 'silence'
              : error instanceof ApiError
                ? error.code
                : 'network',
            retryAfter: error instanceof ApiError ? error.retryAfter : null,
          }));
      } finally {
        window.clearTimeout(timer);
        void client.invalidateQueries({ queryKey: CHATS_KEY });
      }
    },
    [client, board.area, board.polygon, drawn, range, fireId, onAction, onPlan],
  );

  /** Asks the question of an answer that failed again, in the same chat, in place of that answer. */
  const retry = useCallback(
    (answerId: number) => {
      const at = messages.findIndex((message) => message.id === answerId);
      const question = messages[at - 1];
      if (at < 1 || question?.role !== 'user') return;
      setMessages((all) =>
        all.filter((message) => message.id !== answerId && message.id !== question.id),
      );
      void send(question.text, question.attachments);
    },
    [messages, send],
  );

  /** Shows a chat of the person's history; the next question continues it. */
  const open = useCallback(
    async (id: string) => {
      abort.current?.abort();
      const detail = await call(
        api.GET('/api/chats/{chat_id}', { params: { path: { chat_id: id } } }),
      );
      chatId.current = detail.id;
      // the map has what this chat drew, as it drew it: its drawings in order, each in its place
      clearAi();
      for (const message of detail.messages) {
        for (const action of message.actions) {
          if (action.type === 'draw') drawAi(action.shapes, action.replace);
        }
      }
      setMessages(
        detail.messages.map((message) => ({
          id: message.seq,
          role: message.role,
          text: message.text,
          steps: [],
          widgets: message.widgets,
          actions: message.actions,
          at: Date.parse(message.created_at),
          attachments: [],
          status: 'done',
        })),
      );
      next.current = detail.messages.length + 1;
    },
    [clearAi, drawAi],
  );

  /** A plan made from the plan form: the question and the answer are put in the conversation by hand. */
  const runPlan = useCallback(
    async (
      text: string,
      ask: Omit<PlanTurn, 'plan' | 'seconds'>,
      make: () => Promise<FirePlan>,
    ) => {
      const questionId = next.current;
      const answerId = questionId + 1;
      const update = (change: (message: ChatMessage) => ChatMessage) => {
        setMessages((all) => all.map((m) => (m.id === answerId ? change(m) : m)));
      };
      const blank = { steps: [], widgets: [], actions: [], at: Date.now(), attachments: [] };
      const turn: PlanTurn = { ...ask, plan: null, seconds: 0 };
      setMessages((all) => [
        ...all,
        { id: questionId, role: 'user', ...blank, text, status: 'done', work: turn },
        { id: answerId, role: 'assistant', ...blank, text: '', status: 'streaming', work: turn },
      ]);
      next.current += 2;
      const started = Date.now();
      try {
        const plan = await make();
        const seconds = Math.round((Date.now() - started) / 1000);
        update((message) => ({
          ...message,
          at: Date.now(),
          status: 'done',
          work: { ...turn, plan, seconds },
        }));
      } catch (error) {
        update((message) => ({
          ...message,
          status: 'error',
          errorCode: error instanceof ApiError ? error.code : 'network',
        }));
      }
    },
    [],
  );

  const reset = useCallback(() => {
    abort.current?.abort();
    chatId.current = 'new';
    next.current = 1;
    clearAi();
    setMessages([]);
  }, [clearAi]);

  /** Deletes a chat of the history; if it is the one on the screen, the screen starts over. */
  const remove = useCallback(
    async (id: string) => {
      await callEmpty(api.DELETE('/api/chats/{chat_id}', { params: { path: { chat_id: id } } }));
      if (chatId.current === id) reset();
      await client.invalidateQueries({ queryKey: CHATS_KEY });
    },
    [client, reset],
  );

  const stop = useCallback(() => {
    stopped.current = true;
    abort.current?.abort();
  }, []);

  // an answer of the assistant that is coming can be stopped; a plan being made cannot
  const stoppable = messages.some((message) => message.status === 'streaming' && !message.work);
  const busy = messages.some((message) => message.status === 'streaming');
  return {
    messages,
    send,
    stop,
    stoppable,
    retry,
    runPlan,
    busy,
    open,
    reset,
    remove,
    chatId: () => chatId.current,
  };
}
