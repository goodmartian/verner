import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, call } from '../api/client';
import type { Action, FirePlan } from '../api/types';
import { saveFile } from '../lib/saveFile';
import { useBoard } from '../features/board/context';
import { useCountryItems } from '../features/calendar/areas';
import { CalBoard } from '../features/calendar/CalBoard';
import { CalTimeline } from '../features/calendar/CalTimeline';
import { MonthStrip } from '../features/calendar/MonthStrip';
import { ClusterStrip } from '../features/climate/ClusterStrip';
import { clusterCollection } from '../features/climate/days';
import { useClimateArea, useDayFires } from '../features/climate/queries';
import { useCalendarMap } from '../features/calendar/useCalendarMap';
import { usePicked } from '../features/calendar/queries';
import { longMonthYear } from '../features/calendar/text';
import { WidgetActionsContext, type WidgetActions } from '../features/chat/actions';
import { AiPanel, type Addable, type ChatVariant, type Suggestion } from '../features/chat/AiPanel';
import { formatDayShort } from '../features/fires/text';
import type { Attachment } from '../features/chat/attachments';
import { useChat, type ChatContext } from '../features/chat/useChat';
import { useFiresState } from '../features/fires/context';
import { WIND_MODES, useWeatherState } from '../features/weather/context';
import { weatherView } from '../features/weather/showWeather';
import { useWeatherLegend } from '../features/weather/queries';
import { FireStrip } from '../features/fires/FireStrip';
import { FiresList, FireView, RegionChip } from '../features/fires/FiresSide';
import { PassTimeline } from '../features/fires/PassTimeline';
import { coverImage, coverKey } from '../features/fires/cover';
import { useLandCover } from '../features/fires/queries';
import { useBuildPlan, useShowPlan, useShownFire } from '../features/fires/usePlan';
import { useFireMap } from '../features/fires/useFireMap';
import type { MapPadding } from '../features/map/framing';
import { RegionPicker } from '../features/region/RegionPicker';
import { AreaName } from '../features/calendar/AreaName';
import { useAreaName } from '../features/calendar/areas';
import { localName, type LangPref } from '../i18n/lang';
import { areaId, useConfig } from '../config/context';
import { useI18n } from '../i18n/context';
import { useElementRect } from '../lib/useElementRect';
import { useMediaQuery } from '../lib/useMediaQuery';
import { Guard } from '../ui/Guard';
import { Ph } from '../ui/Ph';
import { PopupMenu } from '../ui/PopupMenu';
import { Segments } from '../ui/Segments';
import { folded } from './foldOnScroll';
import { freePart, GAP, stripHeight, type PanelBox } from './freePart';
import type { LngLat } from '../features/map/draw/geometry';

export type Mode = 'fires' | 'cal';
// on a narrow screen the column shows either the fires and the calendar (by the mode) or the assistant
type MobileTab = 'fires' | 'ai';

// the map library is most of the weight: the panels appear first
const MapStage = lazy(() =>
  import('../features/map/MapStage').then((module) => ({ default: module.MapStage })),
);

// the calendar remembers whether its assistant column is open or folded to a strip
const CAL_CHAT = 'senda.cal.chat';
function readCalChat(): ChatVariant {
  try {
    return localStorage.getItem(CAL_CHAT) === 'bar' ? 'bar' : 'panel';
  } catch {
    return 'panel';
  }
}
function saveCalChat(value: ChatVariant) {
  try {
    localStorage.setItem(CAL_CHAT, value);
  } catch {
    // the state is a convenience: without storage it starts open again
  }
}

// the width from which the page has two columns (60rem)
const WIDE = 960;

/** The app: the map under two floating panels, the board of the tab and the assistant. */
export function Shell() {
  const { t, lang, pref, setPref } = useI18n();
  const board = useBoard();
  const config = useConfig();
  const fires = useFiresState();
  const areaName = useAreaName();
  const [mode, setMode] = useState<Mode>('cal');
  // the fires are asked by place: the board gives them the place behind an outline drawn on the statistics
  const { setOnFires } = board;
  useEffect(() => {
    setOnFires(mode === 'fires');
  }, [setOnFires, mode]);
  const weather = useWeatherState();
  const weatherOn = useWeatherLegend(mode === 'fires').data?.available === true;
  // the calendar opens first: its assistant is the column on the left
  const [chat, setChat] = useState<ChatVariant>(readCalChat);
  const [wide, setWide] = useState(false);
  const [sideOn, setSideOn] = useState(true);
  const [calBig, setCalBig] = useState(false);
  const [mtab, setMtab] = useState<MobileTab>('fires');
  const [attachments, setAttachments] = useState<readonly Attachment[]>([]);
  const [regionOpen, setRegionOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [slot, setSlot] = useState<HTMLDivElement | null>(null);
  const app = useRef<HTMLDivElement>(null);
  const [focusKey, setFocusKey] = useState(0);
  const foot = useRef<HTMLDivElement>(null);
  // the button the settings menu hangs from: the gear of the head, of the tabs or of the assistant
  const gear = useRef<HTMLElement | null>(null);
  const narrow = useMediaQuery('(max-width: 60rem)');
  const countries = useCountryItems();

  // opening anything the assistant names shows the map on a narrow screen too, not the conversation
  const tab = useCallback((value: Mode) => {
    setMode(value);
    setMtab('fires');
    // the calendar has the assistant as its column on the left: the line at the bottom is for the map of the fires
    if (value === 'cal') setChat(readCalChat());
  }, []);

  // a press on a tab: the fires have the line at the bottom (the panel of the chat would stand over their list)
  const pressTab = (value: Mode) => {
    tab(value);
    if (value === 'fires') setChat('bar');
  };

  const { select: selectFire, setPlanning, setCrews, setHours, setPlayer, setClock } = fires;
  const { showLayers, setWind } = weather;
  const { setRange, setArea, drawAi, showShape } = board;
  // the assistant moves the board: another period or place of the calendar, a fire, a plan
  const onAction = useCallback(
    (action: Action) => {
      if (action.type === 'set_period') {
        setRange({ from: action.first_month, to: action.last_month });
        tab('cal');
      } else if (action.type === 'set_area') {
        setArea(action.area);
        tab('cal');
      } else if (action.type === 'select_fire') {
        selectFire(action.fire_id);
        tab('fires');
      } else if (action.type === 'draw') {
        // the drawings go on the map where it stands: no other part of the board moves
        drawAi(action.shapes, action.replace);
      } else if (action.type === 'show_weather') {
        // the fire opens, the layers come on, the player stands at the hour
        const view = weatherView(action);
        if (view.fireId) selectFire(view.fireId);
        showLayers(view.layers);
        if (view.wind) setWind('all');
        if (view.clock) {
          setPlayer(true);
          setClock(view.clock);
        }
        tab('fires');
      } else {
        // open_plan: the fire opens with the plan form and what the assistant planned for
        selectFire(action.fire_id);
        if (action.crews) setCrews(action.crews);
        if (action.hours === 1 || action.hours === 3 || action.hours === 6) setHours(action.hours);
        setPlanning(true);
        tab('fires');
      }
    },
    [
      setRange,
      setArea,
      selectFire,
      setPlanning,
      setCrews,
      setHours,
      showLayers,
      setWind,
      setPlayer,
      setClock,
      drawAi,
      tab,
    ],
  );
  // a plan goes on the map: from the button of its card (with the dock), and by itself when the assistant makes it
  const putPlan = useShowPlan();
  const showPlan = useCallback(
    (plan: FirePlan, dock = true) => {
      putPlan(plan, dock);
      tab('fires');
    },
    [putPlan, tab],
  );
  const planMade = useCallback(
    (plan: FirePlan) => {
      showPlan(plan, false);
    },
    [showPlan],
  );
  const { messages, send, stop, stoppable, retry, runPlan, busy, open, reset, remove, chatId } =
    useChat(onAction, planMade);
  const shownFire = useShownFire();
  const planner = useBuildPlan();
  const dockOpen = fires.dock && mode === 'fires';
  // the ground under the open fire comes on its own: a tile that waits while it comes, none when the server has no tile of it
  const ground = useLandCover(mode === 'fires' ? fires.fireId : null, fires.pass);
  const landCover = ground.data ?? null;
  const cover = useMemo(
    () =>
      landCover
        ? {
            image: coverImage(landCover),
            bbox: landCover.bbox,
            attribution: landCover.attribution,
            loading: false,
            key: coverKey(landCover).map((item) => ({
              id: item.id,
              name: localName(item.name, lang),
              color: item.color,
            })),
          }
        : ground.isPending && ground.fetchStatus !== 'idle'
          ? { image: null, bbox: [], attribution: null, loading: true, key: [] }
          : null,
    [landCover, ground.isPending, ground.fetchStatus, lang],
  );
  const fireMap = useFireMap(mode === 'fires');
  const dayFires = useDayFires(board.day, useClimateArea(board.area)).data;
  const clusters = useMemo(() => clusterCollection(dayFires), [dayFires]);
  const calendarMap = useCalendarMap(mode === 'cal');
  const slotRect = useElementRect(mode === 'cal' ? slot : null);
  const [aiEl, setAiEl] = useState<HTMLElement | null>(null);
  const [sideEl, setSideEl] = useState<HTMLElement | null>(null);
  const aiRect = useElementRect(aiEl);
  const sideRect = useElementRect(sideEl);
  // a fire opens, or the list comes back, from the top: the way back is never scrolled out of sight
  useEffect(() => {
    sideEl?.scrollTo({ top: 0 });
  }, [sideEl, fires.fireId]);

  // stable, so the boards that take them (and do not change with the page) are not drawn again each time the page is
  const openRegion = useCallback(() => {
    setRegionOpen(true);
  }, []);
  const openCalendar = useCallback(() => {
    tab('cal');
  }, [tab]);

  // numbers of the layout the stylesheet reads: heights of the head and the foot, where the window of the calendar's map is
  useEffect(() => {
    const element = app.current;
    if (!element) return;
    const sideEl = element.querySelector<HTMLElement>('.side');
    const headEl = element.querySelector<HTMLElement>('.side-head');
    const calHead = element.querySelector<HTMLElement>('.cal-head');
    const footEl = foot.current;
    // a value that has not changed is not written again: the root's style stays as it is and nothing below restyles
    const write = (target: HTMLElement, name: string, value: string) => {
      if (target.style.getPropertyValue(name) !== value) target.style.setProperty(name, value);
    };
    const set = (name: string, value: string) => {
      write(element, name, value);
    };
    // the foot as it is with one line of text: the field grows by its lines, the rest of the foot does not.
    // The layout is built on this height, so typing moves nothing but the field itself
    // the pill a scrolled board folds the line into is lower than the line: the layout keeps the height of the full line
    let lastLine = parseFloat(element.style.getPropertyValue('--foot-h')) || 0;
    const footLine = () => {
      if (!footEl) return 0;
      const field = footEl.querySelector('textarea');
      if (!field) return footEl.offsetHeight;
      const box = footEl.querySelector('.c-box');
      if (lastLine && box && getComputedStyle(box).getPropertyValue('--bar-pill').trim() === '1')
        return lastLine;
      const style = getComputedStyle(field);
      // one line of text with the field's padding, never under its min-height: what the stylesheet gives the empty field
      const line =
        parseFloat(style.lineHeight) +
        parseFloat(style.paddingTop) +
        parseFloat(style.paddingBottom);
      lastLine =
        footEl.offsetHeight - field.offsetHeight + Math.max(parseFloat(style.minHeight), line);
      return lastLine;
    };
    const place = () => {
      const ai = element.querySelector<HTMLElement>('.ai');
      if (!ai || !sideEl || !footEl) return;
      // what the open panels on the left leave free of the window: the line of the chat, the toolbar and the player are
      // centred on that. The calendar has its own columns and is left alone.
      const wideScreen = innerWidth >= WIDE;
      const panels: PanelBox[] = [];
      if (mode !== 'cal' && wideScreen) {
        const list = sideEl.getBoundingClientRect();
        if (list.width) panels.push({ right: list.right, bottom: list.bottom });
        // the panel of the chat slides in, so its place is read from the layout (offset*), which the slide does not move
        if (chat === 'panel')
          panels.push({
            right: ai.offsetLeft + ai.offsetWidth,
            bottom: ai.offsetTop + ai.offsetHeight,
          });
      }
      // the player (hidden while it is closed) and the toolbar, when it lies along the bottom, stand above the line of the chat
      const tools = element.querySelector<HTMLElement>('.tools');
      const player = element.querySelector<HTMLElement>('.bottom');
      const { centre, room } = freePart(
        {
          width: innerWidth,
          height: innerHeight,
          strip: stripHeight({
            foot: footLine(),
            tools: element.dataset.tools === 'h' ? (tools?.offsetHeight ?? 0) : 0,
            player: player?.offsetHeight ?? 0,
          }),
        },
        panels,
      );
      const natural = Math.min(600, Math.max(440, innerWidth * 0.38));
      // a line that does not fit in the free part is narrowed; it never goes under a panel
      const width = mode !== 'cal' && wideScreen ? Math.min(natural, room) : ai.offsetWidth;
      // calendar: the line stands over the board, which scrolls under it; the map window beside it reaches the bottom free
      const board =
        mode === 'cal' && wideScreen ? element.querySelector<HTMLElement>('.cal-body') : null;
      const boardBox = board?.getBoundingClientRect();
      const middle = boardBox?.width ? boardBox.left + boardBox.width / 2 : centre;
      set('--bar-x', `${String(Math.round(middle - width / 2 - GAP))}px`);
      set('--bar-c', `${String(Math.round(middle))}px`);
      set('--bar-max', `${String(Math.round(room))}px`);
    };
    const measure = () => {
      // the root gets the foot of one line; the chat itself gets its real height, which only its own box reads
      if (footEl) {
        set('--foot-h', `${String(Math.ceil(footLine()))}px`);
        const ai = element.querySelector<HTMLElement>('.ai');
        if (ai) write(ai, '--foot-h', `${String(Math.ceil(footEl.offsetHeight))}px`);
      }
      if (sideEl) set('--side-h', `${String(Math.ceil(sideEl.offsetHeight))}px`);
      if (headEl) set('--head-h', `${String(Math.ceil(headEl.offsetHeight))}px`);
      if (calHead) set('--cal-head-w', `${String(Math.ceil(calHead.offsetWidth))}px`);
      place();
    };
    const observer = new ResizeObserver(measure);
    const panel = element.querySelector<HTMLElement>('.ai');
    for (const item of [sideEl, headEl, calHead, footEl, panel]) if (item) observer.observe(item);
    window.addEventListener('resize', measure);
    // the player opens and the toolbar lies down or stands up by the attributes of the app
    const attributes = new MutationObserver(measure);
    attributes.observe(element, {
      attributes: true,
      attributeFilter: ['data-player', 'data-tools'],
    });
    const stood = element.querySelector<HTMLElement>('.bottom');
    if (stood) observer.observe(stood);
    measure();
    return () => {
      attributes.disconnect();
      observer.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [mode, chat, sideOn, wide]);

  // calendar with the chat folded: once the board is scrolled, the line over it folds into a pill (the stylesheet keeps
  // it full while the field has focus, text, an attachment or an answer running). Written only when the state turns
  useEffect(() => {
    const element = app.current;
    const ai = element?.querySelector<HTMLElement>('.ai');
    if (!element || !ai || mode !== 'cal' || chat !== 'bar' || narrow) return;
    const sync = (top: number) => {
      const was = ai.dataset.scrolled === 'on';
      const now = folded(was, top);
      // 'off' only after a fold, so the line does not play the unfold on the first look at the board
      if (now !== was) ai.dataset.scrolled = now ? 'on' : 'off';
    };
    // the board remounts with the period and the section, so its scroll is caught on the way down from the app
    const onScroll = (event: Event) => {
      if (event.target instanceof HTMLElement && event.target.classList.contains('cal-body'))
        sync(event.target.scrollTop);
    };
    element.addEventListener('scroll', onScroll, { capture: true, passive: true });
    const board = element.querySelector<HTMLElement>('.cal-body');
    if (board) sync(board.scrollTop);
    return () => {
      element.removeEventListener('scroll', onScroll, { capture: true });
      delete ai.dataset.scrolled;
    };
  }, [mode, chat, narrow]);

  useEffect(() => {
    const element = app.current;
    if (!element) return;
    // no slot (another tab, or a phone): the window of the map is not placed, and the next time it is, it waits
    if (!slotRect || narrow) {
      delete element.dataset.cm;
      return;
    }
    element.style.setProperty('--cm-l', `${String(Math.round(slotRect.left))}px`);
    element.style.setProperty('--cm-t', `${String(Math.round(slotRect.top))}px`);
    element.style.setProperty('--cm-w', `${String(Math.round(slotRect.width))}px`);
    element.style.setProperty('--cm-h', `${String(Math.round(slotRect.height))}px`);
    // the panels slide into place for a moment after the tab or the chat changes: the window shows once the slot has stopped moving
    delete element.dataset.cm;
    const settled = window.setTimeout(() => {
      element.dataset.cm = 'on';
    }, 200);
    return () => {
      window.clearTimeout(settled);
    };
  }, [slotRect, narrow]);

  const fireOpen = fires.fireId !== null;
  // the map frames the region in what the panels leave free
  // the column on the left holds both panels: the wider of them is what the map leaves free
  // (the calendar frames its own window, which the column does not touch)
  const column =
    mode === 'cal' ? 0 : Math.round(Math.max(aiRect?.width ?? 0, sideRect?.width ?? 0));
  const padding = useMemo<MapPadding>(() => {
    if (narrow) return { top: 48, bottom: 100, left: 24, right: 56 };
    if (mode === 'cal') {
      return calBig
        ? { top: 88, bottom: 32, left: 32, right: 32 + 56 }
        : { top: 64, bottom: 20, left: 20, right: 20 };
    }
    // an open fire has its strip across the top of the map
    return { top: fireOpen ? 96 : 48, bottom: 140, left: column + GAP + 40, right: GAP + 48 + 40 };
  }, [narrow, mode, calBig, fireOpen, column]);

  const attach = (item: Attachment) => {
    setAttachments((now) => [
      ...now.filter((x) => JSON.stringify(x) !== JSON.stringify(item)),
      item,
    ]);
    setChat('panel');
    // on a phone the chat is a tab of the sheet: the figure goes where the question is written
    setMtab('ai');
    setFocusKey((now) => now + 1);
  };
  const attachMonth = (month: string) => {
    if (!board.area) return;
    if ('polygon' in board.area) {
      const drawn = board.drawn.find((item) => item.points === board.polygon);
      if (drawn) askAboutArea(drawn.id);
      return;
    }
    if (!('id' in board.area)) return;
    attach({
      kind: 'month',
      month,
      area: board.area,
      label: areaName ? `${longMonthYear(lang, month)}, ${areaName}` : longMonthYear(lang, month),
    });
  };
  const askAboutShape = (shape: {
    id: string;
    label: string | null;
    points: readonly LngLat[];
    role: 'area' | 'safe_zone';
  }) => {
    attach({
      kind: 'area',
      id: shape.id,
      points: shape.points,
      n: 0,
      role: shape.role,
      ...(shape.label ? { label: shape.label } : {}),
    });
  };
  const askAboutArea = (id: string) => {
    const area = board.drawn.find((item) => item.id === id);
    if (!area) return;
    const number = board.drawn.indexOf(area) + 1;
    attach({ kind: 'area', id, points: area.points, n: number, role: area.role });
  };

  const picked = usePicked();
  const context: ChatContext = {
    tab: mode === 'cal' ? 'calendar' : 'fires',
    areaName: areaName ?? null,
    month: mode === 'cal' ? (picked ?? null) : null,
  };
  const addable: readonly Addable[] = [
    ...(mode === 'cal' && picked
      ? [
          {
            key: 'month',
            icon: 'calendar-dots' as const,
            label: t('chat.addMonth', { m: longMonthYear(lang, picked) }),
            onPick: () => {
              attachMonth(picked);
            },
          },
        ]
      : []),
    ...(mode === 'cal' && board.day
      ? [
          {
            key: 'day',
            icon: 'calendar-dots' as const,
            label: t('chat.addDay', { d: formatDayShort(lang, board.day) }),
            onPick: () => {
              const day = board.day;
              if (day)
                attach({
                  kind: 'fact',
                  label: t('chat.day'),
                  value: formatDayShort(lang, day),
                  area: areaName ?? '',
                  period: day,
                });
            },
          },
        ]
      : []),
    ...board.drawn.map((area, index) => ({
      key: area.id,
      icon: 'polygon' as const,
      label: t('att.area', { n: index + 1 }),
      onPick: () => {
        askAboutArea(area.id);
      },
    })),
  ];

  // the button of an open fire turns the plan form on in the conversation
  const startPlan = () => {
    setChat('panel');
    // on a phone the form is in the assistant's tab
    setMtab('ai');
    fires.setPlanning(true);
  };

  // the plan form asks the planner; the question and the answer go into the conversation
  const makePlan = (note: string) => {
    if (!shownFire) return;
    const { brief } = fires;
    const place = shownFire.summary.nearest_place.name;
    const entries = brief.marks.filter((mark) => mark.kind === 'entry').length;
    fires.setPlanning(false);
    setChat('panel');
    void runPlan(
      `${t('pl.brief', { fi: place })}${note ? ` ${note}` : ''}`,
      {
        fire: shownFire,
        crews: brief.crews,
        hours: brief.hours,
        entries,
        hots: brief.marks.length - entries,
        area: brief.area !== null,
      },
      () => planner.build(),
    );
  };

  const openSettings = (button: HTMLElement) => {
    gear.current = button;
    setSettingsOpen((now) => !now);
  };
  // the buttons inside answers move the board the way the assistant's own actions do
  const { select, setHovered } = fires;
  const widgetActions = useMemo<WidgetActions>(
    () => ({
      openFire: (id) => {
        select(id);
        tab('fires');
      },
      showPeriod: (area, from, to) => {
        setArea(area);
        setRange({ from, to });
        tab('cal');
      },
      showArea: (code) => {
        // a drawn area is shown by its corners; any other place by its code
        const drawn = board.drawn.find((item) => item.id === code);
        if (drawn) board.showDrawn(drawn.points);
        else setArea(code);
        tab('cal');
      },
      hoverFire: setHovered,
      showShape,
      showPlan: (plan) => {
        showPlan(plan);
      },
      addMonth: attachMonth,
      addFact: (fact) => {
        attach({ kind: 'fact', ...fact });
      },
      downloadFile: async (file) => {
        const blob = await call(
          api.GET('/api/chats/{chat_id}/files/{file_id}', {
            params: { path: { chat_id: chatId(), file_id: file.id } },
            parseAs: 'blob',
          }),
        );
        saveFile(blob, file.name);
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- attachMonth is rebuilt each render and reads the board
    [select, setArea, setRange, setHovered, showShape, showPlan, tab, board],
  );

  const suggestions = useMemo<readonly Suggestion[]>(() => {
    const months = attachments.filter((item) => item.kind === 'month').length;
    if (mode === 'cal' && months > 1) {
      return [
        { text: t('chat.months.1'), icon: 'arrows-left-right' },
        { text: t('chat.months.2'), icon: 'trend-up' },
      ];
    }
    if (mode === 'cal' && months === 1) {
      return [
        { text: t('chat.month.1'), icon: 'question' },
        { text: t('chat.month.2'), icon: 'arrows-left-right' },
        { text: t('chat.month.3'), icon: 'map-pin' },
      ];
    }
    // the questions of the calendar name the area and the month on the board
    const place = areaName ?? '';
    const month = picked ? longMonthYear(lang, picked) : '';
    return mode === 'cal'
      ? place && month
        ? [
            { text: t('chat.cal.1', { a: place, m: month }), icon: 'question' },
            { text: t('chat.cal.2', { a: place, m: month }), icon: 'arrows-left-right' },
            { text: t('chat.cal.3', { a: place, m: month }), icon: 'map-pin' },
          ]
        : [
            { text: t('chat.calendar.1'), icon: 'trend-up' },
            { text: t('chat.calendar.2'), icon: 'question' },
            { text: t('chat.calendar.3'), icon: 'map-pin' },
          ]
      : [
          { text: t('chat.fires.1'), icon: 'trend-up' },
          { text: t('chat.fires.2'), icon: 'map-pin' },
          { text: t('chat.fires.3'), icon: 'wind' },
        ];
  }, [attachments, mode, t, areaName, picked, lang]);

  const choices: { value: LangPref; label: string }[] = [
    { value: 'auto', label: t('settings.langAuto') },
    ...(config?.languages ?? []).map((item) => ({ value: item.code, label: item.name })),
  ];

  const dataset = {
    'data-mode': mode,
    'data-chat': chat,
    'data-ai': 'on',
    'data-side': sideOn ? 'on' : 'off',
    'data-wide': wide ? 'on' : 'off',
    'data-focus': 'off',
    'data-player': fires.player ? 'on' : 'off',
    'data-calmap': calBig ? 'big' : 'off',
    'data-art': dockOpen ? 'on' : 'off',
    'data-thread': messages.length > 0 ? 'on' : 'off',
    'data-tools': 'h',
    'data-arch': mode === 'cal' ? 'on' : 'off',
    'data-mtab': mtab,
  };

  return (
    <WidgetActionsContext value={widgetActions}>
      <div className="app" id="app" ref={app} {...dataset}>
        <Guard>
          <Suspense fallback={null}>
            <MapStage
              mode={mode}
              padding={padding}
              bounds={mode === 'cal' ? calendarMap.bounds : fireMap.bounds}
              onAskArea={askAboutArea}
              onAskShape={askAboutShape}
              player={fires.player}
              onPlayer={() => {
                fires.setPlayer(!fires.player);
              }}
              overlay={
                mode === 'cal' ? (
                  board.cluster ? (
                    <ClusterStrip />
                  ) : calBig ? (
                    <MonthStrip />
                  ) : null
                ) : (
                  <>
                    <FireStrip />
                    <RegionChip
                      onRegion={() => {
                        setRegionOpen(true);
                      }}
                    />
                  </>
                )
              }
              bottom={
                <>
                  <PassTimeline />
                  <CalTimeline
                    big={calBig}
                    onClose={() => {
                      fires.setPlayer(false);
                    }}
                  />
                </>
              }
              big={calBig}
              onBig={() => {
                setCalBig((now) => !now);
              }}
              legend={fires.plan !== null}
              fires={
                mode === 'fires'
                  ? {
                      data: fireMap.data,
                      onSelect: fires.select,
                      placing: fires.placing,
                      onPlacing: fires.setPlacing,
                      planning: fires.planning,
                      onUseArea: fires.setArea,
                      plan:
                        fires.plan && shownFire ? { plan: fires.plan, detail: shownFire } : null,
                      cover: cover
                        ? {
                            ...cover,
                            on: fires.cover,
                            onToggle: () => {
                              fires.setCover(!fires.cover);
                            },
                          }
                        : null,
                    }
                  : undefined
              }
              calendar={
                mode === 'cal'
                  ? {
                      // a day is picked: its clusters are on the map, not the cells of the month
                      cells: board.day ? null : calendarMap.cells,
                      outline: calendarMap.outline,
                      dayFires: board.day
                        ? {
                            data: clusters,
                            selected: board.cluster,
                            onSelect: (id) => {
                              board.setCluster(id);
                              fires.setPlayer(true);
                            },
                          }
                        : undefined,
                    }
                  : undefined
              }
            />
          </Suspense>
        </Guard>

        <aside ref={setSideEl} className="panel side" aria-label={t('tabs.fires')}>
          <header className="side-head">
            <span className="wordmark">
              <img className="logo" src="/logo.png" alt="" width={24} height={24} />
              Verner
            </span>
            <Segments
              label={t('tabs.label')}
              items={[
                ['cal', t('tabs.calendar'), 'tab-cal'],
                ['fires', t('tabs.fires'), 'tab-fires'],
              ]}
              value={mode}
              onChange={pressTab}
            />
            <button
              type="button"
              className="icon-btn"
              id="settings-btn"
              aria-expanded={settingsOpen}
              aria-haspopup="menu"
              aria-controls="settings"
              aria-label={t('settings.title')}
              onClick={(event) => {
                openSettings(event.currentTarget);
              }}
            >
              <Ph name="gear-six" />
            </button>
            <button
              type="button"
              className="icon-btn"
              id="hide-side"
              aria-expanded={sideOn}
              aria-label={t('side.hide')}
              onClick={() => {
                setSideOn((now) => !now);
              }}
            >
              <Ph name="caret-up" />
            </button>
          </header>

          <section
            className="view"
            id="v-list"
            aria-labelledby="h-list"
            hidden={mode !== 'fires' || fires.fireId !== null}
          >
            <Guard>
              <FiresList onRegion={openRegion} onCalendar={openCalendar} />
            </Guard>
          </section>
          <section
            className="view"
            id="v-fire"
            aria-labelledby="fd-name"
            hidden={mode !== 'fires' || fires.fireId === null}
          >
            <Guard>{fires.fireId !== null ? <FireView onPlan={startPlan} /> : null}</Guard>
          </section>
          <section className="view" id="v-cal" aria-labelledby="h-cal" hidden={mode !== 'cal'}>
            <Guard>
              <CalBoard slotRef={setSlot} onRegion={openRegion} />
            </Guard>
          </section>
        </aside>

        <nav className="m-tabs" aria-label={t('tabs.label')}>
          <Segments
            label={t('tabs.label')}
            items={[
              ['cal', t('tabs.calendar')],
              ['fires', t('tabs.fires')],
              ['ai', t('chat.title')],
            ]}
            value={mtab === 'ai' ? 'ai' : mode}
            onChange={(value) => {
              if (value === 'ai') setMtab('ai');
              else pressTab(value);
            }}
          />
          <button
            type="button"
            className="icon-btn"
            id="settings-btn-m"
            aria-expanded={settingsOpen}
            aria-haspopup="menu"
            aria-controls="settings"
            aria-label={t('settings.title')}
            onClick={(event) => {
              openSettings(event.currentTarget);
            }}
          >
            <Ph name="gear-six" />
          </button>
        </nav>

        <Guard>
          <AiPanel
            variant={chat}
            onVariant={(value) => {
              setChat(value);
              if (mode === 'cal') saveCalChat(value);
            }}
            onSettings={openSettings}
            rootRef={setAiEl}
            wide={wide}
            onWide={() => {
              setWide((now) => !now);
            }}
            messages={messages}
            busy={busy}
            onStop={stoppable ? stop : undefined}
            onRetry={retry}
            onSend={(text, items) => {
              void send(text, items, context);
            }}
            onOpenChat={(id) => {
              void open(id);
              setChat('panel');
            }}
            onDeleteChat={(id) => {
              void remove(id);
            }}
            onNewChat={reset}
            attachments={attachments}
            onAttachments={setAttachments}
            canPlan={mode === 'fires' && fires.fireId !== null}
            onPlan={makePlan}
            dockOpen={dockOpen}
            addable={addable}
            suggestions={suggestions}
            focusKey={focusKey}
            foot={foot}
          />
        </Guard>
      </div>

      <PopupMenu
        anchor={gear}
        open={settingsOpen}
        id="settings"
        label={t('settings.title')}
        align="end"
        onClose={() => {
          setSettingsOpen(false);
        }}
      >
        <div className="menu-label">{t('settings.language')}</div>
        {choices.map((choice) => (
          <button
            key={choice.value}
            type="button"
            className="menu-item"
            role="menuitemradio"
            aria-checked={pref === choice.value}
            onClick={() => {
              setPref(choice.value);
              setSettingsOpen(false);
            }}
          >
            <span>{choice.label}</span>
            <Ph name="check" className="ph-check" />
          </button>
        ))}
        <div className="menu-sep" role="separator" />
        <button
          type="button"
          className="menu-item"
          role="menuitem"
          id="opt-region"
          onClick={() => {
            setSettingsOpen(false);
            setRegionOpen(true);
          }}
        >
          <span>{t('settings.region')}</span>
          <span className="menu-val">
            <AreaName />
          </span>
        </button>
        {mode === 'fires' && weatherOn ? (
          <>
            <div className="menu-sep" role="separator" />
            <div className="menu-label">{t('settings.wind')}</div>
            {WIND_MODES.map((value) => (
              <button
                key={value}
                type="button"
                className="menu-item"
                role="menuitemradio"
                aria-checked={weather.wind === value}
                onClick={() => {
                  weather.setWind(value);
                  setSettingsOpen(false);
                }}
              >
                <span>{t(`settings.wind.${value}`)}</span>
                <Ph name="check" className="ph-check" />
              </button>
            ))}
            <div className="menu-sep" role="separator" />
            <button
              type="button"
              className="menu-item"
              role="menuitemcheckbox"
              aria-checked={weather.animation}
              onClick={() => {
                weather.setAnimation(!weather.animation);
                setSettingsOpen(false);
              }}
            >
              <span>{t('settings.windAnimation')}</span>
              <Ph name="check" className="ph-check" />
            </button>
          </>
        ) : null}
      </PopupMenu>

      <RegionPicker
        key={regionOpen ? 'open' : 'closed'}
        open={regionOpen}
        onClose={() => {
          setRegionOpen(false);
        }}
        countries={countries}
        value={areaId(board.area)}
        onPick={(id) => {
          // an area drawn on the map is shown by its corners; any other place by its code
          const drawn = board.drawn.find((area) => area.id === id);
          if (drawn) board.showDrawn(drawn.points);
          else board.setArea(id);
        }}
        showFires={mode === 'fires'}
        areas={
          mode === 'cal'
            ? board.drawn.map((area, index) => ({
                id: area.id,
                name: t('att.area', { n: index + 1 }),
              }))
            : []
        }
      />
    </WidgetActionsContext>
  );
}
