import { memo, type Ref } from 'react';
import { AreaCalendarBoard } from './AreaCalendarBoard';

interface CalBoardProps {
  slotRef: Ref<HTMLDivElement>;
  onRegion: () => void;
}

/** What the calendar tab holds: the region, the empty window for the map, then the board of the area. */
// a page that re-renders for its own reasons (a dialog opens, a tab changes) leaves the board of the area alone
export const CalBoard = memo(function CalBoard({ slotRef, onRegion }: CalBoardProps) {
  return <AreaCalendarBoard slotRef={slotRef} onRegion={onRegion} />;
});
