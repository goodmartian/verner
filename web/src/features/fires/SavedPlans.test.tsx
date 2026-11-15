import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { PLAN_RECORD } from '../../test/fireFixtures';
import { apiError, json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { useFiresState } from './context';
import { SavedPlans } from './SavedPlans';

const ITEM = {
  id: PLAN_RECORD.id,
  title: PLAN_RECORD.title,
  fire_id: PLAN_RECORD.fire_id,
  near: 'Santo Tomé',
  crews: 2,
  hours: 3,
  created_at: PLAN_RECORD.created_at,
};

function Shelf() {
  const { record } = useFiresState();
  return (
    <>
      <SavedPlans />
      <output>{record ? `open ${String(record.id)}` : 'closed'}</output>
    </>
  );
}

afterEach(() => {
  localStorage.clear();
});

describe('the saved plans', () => {
  it('lists the plans, opens one as it was made, and deletes one', async () => {
    let list = [ITEM];
    const calls = mockApi({
      'GET /api/plans': () => json(200, list),
      [`GET /api/plans/${String(ITEM.id)}`]: () => json(200, PLAN_RECORD),
      [`DELETE /api/plans/${String(ITEM.id)}`]: () => {
        list = [];
        return new Response(null, { status: 204 });
      },
    });
    renderApp(<Shelf />);
    await userEvent.click(await screen.findByText(ITEM.title));
    expect(await screen.findByRole('status')).toHaveTextContent('open 7');
    await userEvent.click(
      screen.getByRole('button', { name: new RegExp(`Delete plan: ${ITEM.title}`) }),
    );
    await waitFor(() => {
      expect(screen.queryByText(ITEM.title)).not.toBeInTheDocument();
    });
    expect(calls.some((call) => call.method === 'DELETE')).toBe(true);
  });

  it('says quietly that the plans are not available when the storage is down', async () => {
    mockApi({ 'GET /api/plans': () => apiError(503, 'storage_unavailable') });
    renderApp(<Shelf />);
    expect(await screen.findByText('Saved plans are temporarily unavailable')).toBeInTheDocument();
  });
});
