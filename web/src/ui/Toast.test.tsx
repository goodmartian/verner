import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Toast } from './Toast';

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe('Toast', () => {
  it('says its message, and goes by itself after a few seconds', () => {
    render(<Toast message="No data for this hour" />);
    expect(screen.getByRole('status')).toHaveTextContent('No data for this hour');
    act(() => {
      vi.advanceTimersByTime(4100);
    });
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
  });

  it('does not come back while the same state goes on, and comes again after it was gone', () => {
    const { rerender } = render(<Toast message="No data for this hour" />);
    act(() => {
      vi.advanceTimersByTime(4100);
    });
    rerender(<Toast message="No data for this hour" />);
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
    rerender(<Toast message={null} />);
    rerender(<Toast message="No data for this hour" />);
    expect(screen.getByRole('status')).toHaveTextContent('No data for this hour');
  });
});
