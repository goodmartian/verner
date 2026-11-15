import type { FetchResponse } from 'openapi-fetch';
import type { components, paths } from './schema';

type Schemas = components['schemas'];

/** The data of a widget as the client reads it (the same numbers the history of a chat carries). */
type WidgetData<Type extends Widget['type']> = Extract<Widget, { type: Type }>['data'];
export type Summary = WidgetData<'period_summary'>;
export type MonthPoint = Schemas['MonthPoint'];
export type ProvinceTable = Schemas['ProvinceTable'];
export type ProvinceRow = Schemas['ProvinceRow'];
export type MonthDetail = WidgetData<'month_detail'>;
export type Check = WidgetData<'forecast_check'>;
export type Regions = Schemas['Regions'];
export type Region = Schemas['Region'];
export type CountryAnswer = Schemas['CountryAnswer'];
export type AreaStats = Schemas['AreaStats'];
export type ChatQuestion = Schemas['ChatQuestion'];

/** What a request answers with, as the client reads it. */
type Answer<Path extends keyof paths> = paths[Path] extends { get: infer Operation }
  ? NonNullable<FetchResponse<Operation & object, object, 'application/json'>['data']>
  : never;

type ChatDetail = Answer<'/api/chats/{chat_id}'>;
export type Widget = ChatDetail['messages'][number]['widgets'][number];
export type Action = ChatDetail['messages'][number]['actions'][number];

/** One event of the answer stream; widgets and actions are the same as in a chat's history. */
export type ChatEvent =
  | Schemas['StartEvent']
  | Schemas['StepEvent']
  | Schemas['TextEvent']
  | { event: 'widget'; data: Widget }
  | { event: 'action'; data: Action }
  | Schemas['DoneEvent']
  | Schemas['ErrorEvent'];

export type FireList = Answer<'/api/fires'>;
export type FireSummary = FireList['fires'][number];
export type PassInfo = FireList['passes'][number];
export type FireDetail = Answer<'/api/fires/{fire_id}'>;
/** The plan as the client reads the answer of `POST /api/fires/{id}/plan`. */
export type FirePlan = NonNullable<
  FetchResponse<paths['/api/fires/{fire_id}/plan']['post'], object, 'application/json'>['data']
>;
export type PlanRequest = Schemas['PlanRequest'];
export type AccessRoute = Answer<'/api/fires/{fire_id}/access-route'>;
export type PlanCrew = FirePlan['crews'][number];
export type PlanIssue = FirePlan['issues'][number];
export type LandCover = Schemas['LandCover'];

export type WeatherLegend = Answer<'/api/weather/legend'>;
export type LegendLayer = WeatherLegend['layers'][number];
export type LegendBand = LegendLayer['bands'][number];
export type FireWeather = Answer<'/api/weather/fires'>;
export type FireSeries = FireWeather['fires'][number];
export type WindPoints = Answer<'/api/weather/wind'>;
export type WeatherAt = Answer<'/api/weather/at'>;
export type GridBounds = Answer<'/api/weather/grid/bounds'>;

export type MonthDays = Answer<'/api/calendar/days'>;
export type DayFires = Answer<'/api/calendar/fires'>;
export type FireCluster = DayFires['fires'][number];

export type ShowWeatherAction = Extract<Action, { type: 'show_weather' }>;
export type DrawAction = Extract<Action, { type: 'draw' }>;
/** A shape the assistant draws on the map, already worked out by the server. */
export type DrawShape = DrawAction['shapes'][number];
/** A kept plan: the request, the plan and the card of the fire as they were made. */
export type PlanRecord = NonNullable<
  FetchResponse<paths['/api/plans/{plan_id}']['get'], object, 'application/json'>['data']
>;
