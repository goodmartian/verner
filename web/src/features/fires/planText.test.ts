import { INTEGER_ZONE } from '../../test/configFixtures';
import { describe, expect, it } from 'vitest';
import { FIRE_DETAIL, PLAN } from '../../test/fireFixtures';
import { translate } from '../../i18n/translate';
import type { MessageKey } from '../../i18n/en';
import {
  crewKeys,
  crewsText,
  goingCrews,
  planCopy,
  planReport,
  planSteps,
  reviewRows,
} from './planText';

const tEn = (key: MessageKey, params?: Record<string, string | number>) =>
  translate('en', key, params);
const tRu = (key: MessageKey, params?: Record<string, string | number>) =>
  translate('ru', key, params);

describe('crewsText', () => {
  it('counts crews in the form the language needs', () => {
    expect(crewsText(tEn, 'en', 1)).toBe('1 crew');
    expect(crewsText(tEn, 'en', 2)).toBe('2 crews');
    expect(crewsText(tRu, 'ru', 5)).toBe('5 бригад');
    expect(crewsText(tRu, 'ru', 2)).toBe('2 бригады');
  });
});

describe('the plan as text', () => {
  it('sends the crews the planner did not leave out', () => {
    expect(goingCrews(PLAN).map((crew) => crew.number)).toEqual([1]);
  });

  it('reads the situation, the task and the safety from the numbers of the plan', () => {
    const report = planReport(tEn, 'en', PLAN, FIRE_DETAIL, INTEGER_ZONE);
    expect(report.situation).toContain('252 ha');
    expect(report.situation).toContain('35 detections');
    expect(report.task).toContain('2 crews, 3 h window');
    expect(report.task).toContain('hotspot 1');
    expect(report.safety).toContain('First crew leaves at');
  });

  it('says what a crew leader needs, one line a crew with its entry coordinates', () => {
    const text = planCopy(tEn, 'en', PLAN, FIRE_DETAIL, INTEGER_ZONE);
    expect(text).toContain('Work plan, Santo Tomé');
    expect(text).toContain('Crew 1: enter from the south, to hotspot 1');
    expect(text).toContain('-28.46600, -56.08000');
  });
});

describe('the check of the plan', () => {
  it('has a row for each reason', () => {
    const rows = reviewRows(tEn, 'en', PLAN, PLAN.pass_time, INTEGER_ZONE);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      title: 'Fire reaches the entry',
      level: 'block',
    });
    expect(rows[0]?.sub).toContain('Entry 1');
    expect(rows[1]).toMatchObject({ level: 'info' });
  });

  it('keeps the key of a block, and says it was overruled once it is', () => {
    const [first] = reviewRows(tEn, 'en', PLAN, PLAN.pass_time, INTEGER_ZONE);
    expect(first).toMatchObject({ keys: ['e1'], forced: false });
    const forced = {
      ...PLAN,
      issues: PLAN.issues.map((issue) => (issue.key ? { ...issue, forced: true } : issue)),
    };
    const [after] = reviewRows(tEn, 'en', forced, PLAN.pass_time, INTEGER_ZONE);
    expect(after).toMatchObject({
      forced: true,
      level: 'forced',
      sub: expect.stringContaining('Included by you') as string,
    });
  });

  it('knows what to send to include a crew that was left out', () => {
    const [going, left] = PLAN.crews;
    if (!going || !left) throw new Error('the plan has two crews');
    // a block of the entry is overruled from its row, a strong wind from the crew
    expect(crewKeys(PLAN, left)).toEqual([]);
    const windy = {
      ...PLAN,
      issues: [{ ...PLAN.issues[0], kind: 'wind' as const, key: 'wind' }],
    };
    expect(crewKeys(windy as typeof PLAN, { ...left, held: ['wind'] })).toEqual(['wind']);
    expect(crewKeys(PLAN, going)).toEqual([]);
  });

  it('says how long the trail is among the steps', () => {
    const trail = {
      ...PLAN,
      crews: PLAN.crews.map((crew) => ({
        ...crew,
        on_trail: true,
        crosses_wet_ground: true,
        length_m: 2400,
      })),
    };
    const steps = planSteps(tEn, 'en', trail, FIRE_DETAIL, { entries: 0, hots: 0 }, INTEGER_ZONE);
    expect(steps.find((step) => step.label.startsWith('Laying trails'))?.result).toBe(
      'up to 2.4 km on foot, around water and marsh',
    );
  });

  it('offers to rebuild when the map shows another pass', () => {
    const rows = reviewRows(tEn, 'en', PLAN, '2026-10-28T12:00:00Z', INTEGER_ZONE);
    expect(rows[0]).toMatchObject({ rebuild: true, level: 'info' });
  });
});
