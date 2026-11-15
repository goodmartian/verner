import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, useRef } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { FirePlan } from '../../api/types';
import { FIRE, FIRE_DETAIL, PLAN, PLAN_RECORD } from '../../test/fireFixtures';
import { apiError, json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { useFiresState } from './context';
import { PlanDock } from './PlanDock';
import { useShowPlan } from './usePlan';

afterEach(() => {
  vi.unstubAllGlobals();
});

const routes = {
  [`GET /api/fires/${FIRE.id}`]: () => json(200, FIRE_DETAIL),
  [`POST /api/fires/${FIRE.id}/plan`]: () => json(200, PLAN),
  'POST /api/plans': () => json(201, PLAN_RECORD),
};

/** Opens the fire and puts the plan on the board, then shows the window. */
function Dock({ plan = PLAN, onClose = vi.fn() }: { plan?: FirePlan; onClose?: () => void }) {
  const fires = useFiresState();
  const { select, setPlan } = fires;
  // once: the board hands out new functions at every change, and the setup must not run over the test
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    done.current = true;
    select(FIRE.id);
    setPlan(plan);
  }, [select, setPlan, plan]);
  return <PlanDock wide={false} onWide={vi.fn()} onClose={onClose} />;
}

describe('the plan window', () => {
  it('tells the facts, a card for each crew and the three parts of the report', async () => {
    mockApi(routes);
    renderApp(<Dock />);
    expect(
      await screen.findByRole('heading', { name: 'Work plan, Santo Tomé' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Window until')).toBeInTheDocument();
    expect(screen.getByText('First leave')).toBeInTheDocument();
    expect(screen.getAllByText('Hotspot 1', { exact: false }).length).toBeGreaterThan(0);
    expect(screen.getByRole('heading', { name: 'Situation' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Task' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Safety' })).toBeInTheDocument();
  });

  it('includes a crew that was left out: the plan is made again with the key of the block', async () => {
    const calls = mockApi(routes);
    renderApp(<Dock />);
    const [include] = await screen.findAllByRole('button', { name: 'Include' });
    await userEvent.click(include ?? document.body);
    await waitFor(() => {
      expect(
        calls.some((call) => call.method === 'POST' && call.path === `/api/fires/${FIRE.id}/plan`),
      ).toBe(true);
    });
    const made = calls.find((call) => call.path === `/api/fires/${FIRE.id}/plan`);
    expect(made?.body).toMatchObject({ overrides: ['e1'] });
  });

  it('says quietly that the ways go in a straight line when there is no vegetation map', async () => {
    mockApi(routes);
    renderApp(<Dock plan={{ ...PLAN, straight_line_only: true }} />);
    expect(await screen.findByText(/vegetation map is not available/)).toBeInTheDocument();
  });

  it('marks the crew the planner left out and leaves room to filter them', async () => {
    mockApi(routes);
    renderApp(<Dock />);
    expect(await screen.findByText(/Left out by the assistant/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Left out 1/ }));
    expect(screen.getByRole('button', { name: /Left out 1/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('keeps the plan on the server once, and goes back to the chat', async () => {
    const onClose = vi.fn();
    const calls = mockApi(routes);
    renderApp(<Dock onClose={onClose} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Save the plan' }));
    expect(await screen.findByRole('button', { name: 'Plan saved' })).toBeDisabled();
    const saves = calls.filter((call) => call.method === 'POST' && call.path === '/api/plans');
    expect(saves).toHaveLength(1);
    expect(saves[0]?.body).toMatchObject({ fire_id: FIRE.id });
    await userEvent.click(screen.getByRole('button', { name: 'Back to the chat' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('says so when the shelf of plans is full, and lets the plan be saved again', async () => {
    mockApi({ ...routes, 'POST /api/plans': () => apiError(409, 'conflict') });
    renderApp(<Dock />);
    await userEvent.click(await screen.findByRole('button', { name: 'Save the plan' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      '100 plans are saved, delete old ones',
    );
    expect(screen.getByRole('button', { name: 'Save the plan' })).toBeEnabled();
  });

  it('says so when every crew is left out', async () => {
    mockApi(routes);
    renderApp(
      <Dock plan={{ ...PLAN, crews: PLAN.crews.map((crew) => ({ ...crew, status: 'block' })) }} />,
    );
    expect(await screen.findByText(/No safe plan/)).toBeInTheDocument();
  });
});

describe('putting a plan on the map', () => {
  function Show({ dock }: { dock?: boolean }) {
    const fires = useFiresState();
    const show = useShowPlan();
    return (
      <>
        <button
          type="button"
          onClick={() => {
            show(PLAN, dock);
          }}
        >
          show
        </button>
        <output aria-label="state">
          {`${fires.fireId ?? ''}:${String(fires.plan === PLAN)}:${String(fires.dock)}`}
        </output>
      </>
    );
  }

  it('selects the fire and sets the plan, and opens the dock when it is the button of a card', async () => {
    mockApi(routes);
    renderApp(<Show />);
    await userEvent.click(screen.getByRole('button', { name: 'show' }));
    expect(screen.getByLabelText('state').textContent).toBe(`${FIRE.id}:true:true`);
  });

  it('leaves the dock shut when the assistant made the plan', async () => {
    mockApi(routes);
    renderApp(<Show dock={false} />);
    await userEvent.click(screen.getByRole('button', { name: 'show' }));
    expect(screen.getByLabelText('state').textContent).toBe(`${FIRE.id}:true:false`);
  });
});
