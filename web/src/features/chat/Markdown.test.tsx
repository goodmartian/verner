import { COUNTRY_ID, REGION_ID } from '../../test/configFixtures';
import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import { FIRE, FIRE_LIST } from '../../test/fireFixtures';
import { json, mockApi } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { WidgetActionsContext, type WidgetActions } from './actions';
import { AnswerText, Block } from './Markdown';

// the parser is loaded on first use: once it is in, every later draw is at once
beforeAll(async () => {
  const { container, unmount } = render(<Block text="**warm**" />);
  await waitFor(() => {
    expect(container.querySelector('strong')).not.toBeNull();
  });
  unmount();
});

describe('Block', () => {
  it('draws bold, emphasis and code', () => {
    const { container } = render(
      <Block text={'**Многолетний тренд, ×0,73.** and *this* and `that`'} />,
    );
    expect(container.querySelector('strong')?.textContent).toBe('Многолетний тренд, ×0,73.');
    expect(container.querySelector('em')?.textContent).toBe('this');
    expect(container.querySelector('code')?.textContent).toBe('that');
    expect(container.textContent).not.toContain('*');
  });

  it('draws lists, ordered and not', () => {
    const { container } = render(<Block text={'- one\n- two\n\n1. a\n2. b'} />);
    expect(container.querySelectorAll('ul > li')).toHaveLength(2);
    expect(container.querySelectorAll('ol > li')).toHaveLength(2);
  });

  it('keeps no HTML: it is not an element, and what looks like one is only text', () => {
    const { container } = render(
      <Block text={'<script>alert(1)</script> <img src=x onerror=alert(1)> <b>bold</b>'} />,
    );
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('b')).toBeNull();
  });

  it('has no headings, tables or images, only their words', () => {
    const { container } = render(
      <Block text={'# Title\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n![alt](https://e.com/x.png)'} />,
    );
    expect(container.querySelector('h1')).toBeNull();
    expect(container.querySelector('table')).toBeNull();
    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).toContain('Title');
  });

  it('makes links of http and https only, opened apart and without a hand to the page', () => {
    const { container } = render(
      <Block
        text={'[good](https://example.com/a) [bad](javascript:alert(1)) [mail](mailto:a@b.c)'}
      />,
    );
    const links = container.querySelectorAll('a');
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute('href', 'https://example.com/a');
    expect(links[0]).toHaveAttribute('target', '_blank');
    expect(links[0]).toHaveAttribute('rel', 'noopener noreferrer');
    expect(container.textContent).toContain('bad');
  });
});

describe('AnswerText', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance'] });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows a text that was there whole at once, in paragraphs', () => {
    render(
      <AnswerText id={1} text={'first\n\nsecond **bold**'} streaming={false} onTyping={vi.fn()} />,
    );
    expect(screen.getByText('first')).toBeInTheDocument();
    expect(screen.getByText('bold').tagName).toBe('STRONG');
  });

  it('writes an answer that is coming out gradually, with no asterisks until they close', () => {
    const onTyping = vi.fn();
    const { container, rerender } = render(
      <AnswerText id={1} text="**Многолетний тренд, ×0,73." streaming onTyping={onTyping} />,
    );
    expect(container.textContent).toBe('');
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(container.textContent.length).toBeGreaterThan(0);
    expect(container.textContent).not.toContain('*');
    expect(container.querySelector('strong')).toBeNull();
    rerender(
      <AnswerText
        id={1}
        text="**Многолетний тренд, ×0,73.**"
        streaming={false}
        onTyping={onTyping}
      />,
    );
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(container.querySelector('strong')?.textContent).toBe('Многолетний тренд, ×0,73.');
    expect(onTyping).toHaveBeenLastCalledWith(1, false);
  });

  it('tells that it is typing until the last of the text is out, even after the answer is over', () => {
    const onTyping = vi.fn();
    const text = 'x'.repeat(400);
    const { rerender } = render(<AnswerText id={7} text={text} streaming onTyping={onTyping} />);
    expect(onTyping).toHaveBeenLastCalledWith(7, true);
    rerender(<AnswerText id={7} text={text} streaming={false} onTyping={onTyping} />);
    expect(onTyping).toHaveBeenLastCalledWith(7, true);
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(onTyping).toHaveBeenLastCalledWith(7, false);
  });

  it('stops its frames when it goes away', () => {
    const { unmount } = render(
      <AnswerText id={1} text={'y'.repeat(2000)} streaming onTyping={vi.fn()} />,
    );
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe('the links of the assistant', () => {
  const hands = (): WidgetActions => ({
    openFire: vi.fn(),
    addMonth: vi.fn(),
    addFact: vi.fn(),
    showPeriod: vi.fn(),
    showArea: vi.fn(),
    hoverFire: vi.fn(),
    showShape: vi.fn(),
    showPlan: vi.fn(),
  });
  const routes = {
    'GET /api/fires': () => json(200, FIRE_LIST),
  };
  const show = (text: string, actions: WidgetActions | null = hands()) =>
    renderApp(
      actions ? (
        <WidgetActionsContext value={actions}>
          <Block text={text} />
        </WidgetActionsContext>
      ) : (
        <Block text={text} />
      ),
    );

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('turns the caption of a drawing into a button that centres the map on it, and leaves a stranger as words', async () => {
    mockApi(routes);
    const actions = hands();
    show('see [the meeting point](shape:A3) and [this](shape:U1)', actions);
    await userEvent.click(await screen.findByRole('button', { name: 'the meeting point' }));
    expect(actions.showShape).toHaveBeenCalledWith('A3');
    expect(screen.queryByRole('button', { name: 'this' })).not.toBeInTheDocument();
    expect(screen.getByText(/this/)).toBeInTheDocument();
  });

  it('turns a fire into a button that opens it, and marks it on the map while the pointer is on it', async () => {
    mockApi(routes);
    const actions = hands();
    show(`a [fire near Santo Tomé](fire:${FIRE.id}) b`, actions);
    const button = await screen.findByRole('button', { name: 'fire near Santo Tomé' });
    // a button in the clothes of a link: nothing opens in another tab
    expect(document.querySelector('a')).toBeNull();
    await userEvent.hover(button);
    expect(actions.hoverFire).toHaveBeenLastCalledWith(FIRE.id);
    await userEvent.unhover(button);
    expect(actions.hoverFire).toHaveBeenLastCalledWith(null);
    await userEvent.click(button);
    expect(actions.openFire).toHaveBeenCalledWith(FIRE.id);
  });

  it('has the words of a fire that is gone from the live data, with a note, and no button', async () => {
    mockApi(routes);
    show('see [the old fire](fire:19990101-9)');
    const note = await screen.findByTitle('The fire is no longer active');
    expect(note).toHaveTextContent('the old fire');
    expect(screen.queryByRole('button', { name: 'the old fire' })).not.toBeInTheDocument();
  });

  it('sets a month, or a run of months, in the area of the board', async () => {
    mockApi(routes);
    const actions = hands();
    show('[October](period:2025-10) and [the autumn](period:2025-10..2026-03)', actions);
    await userEvent.click(screen.getByRole('button', { name: 'October' }));
    expect(actions.showPeriod).toHaveBeenLastCalledWith({ id: COUNTRY_ID }, '2025-10', '2025-10');
    await userEvent.click(screen.getByRole('button', { name: 'the autumn' }));
    expect(actions.showPeriod).toHaveBeenLastCalledWith({ id: COUNTRY_ID }, '2025-10', '2026-03');
  });

  it('sets an area by its code', async () => {
    mockApi(routes);
    const actions = hands();
    show(`in [Chaco](area:${REGION_ID})`, actions);
    await userEvent.click(screen.getByRole('button', { name: 'Chaco' }));
    expect(actions.showArea).toHaveBeenCalledWith(REGION_ID);
  });

  it('keeps web addresses as links and strips every other scheme, leaving the words', () => {
    mockApi(routes);
    const { container } = show(
      '[web](https://example.com) [script](javascript:alert(1)) [data](data:text/html,x) [odd](fire:a b)',
    );
    expect(container.querySelectorAll('a')).toHaveLength(1);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(container.textContent).toContain('script');
    expect(container.textContent).toContain('odd');
  });

  it('is only words where there is no board to move', () => {
    mockApi(routes);
    show('[a fire](fire:20261030-1) and [a month](period:2025-10)', null);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByText(/a fire and a month/)).toBeInTheDocument();
  });
});
