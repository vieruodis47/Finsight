import React from 'react';
import { ResponsiveContainer } from 'recharts';
import { useElementWidth } from '../utils/hooks';

interface ResponsiveChartProps {
  /**
   * Explicit pixel height for this breakpoint. ResponsiveContainer needs a
   * BOUNDED parent — a percentage height inside an unbounded flex column
   * collapses to 0 and the chart renders invisibly. The wrapper div below owns
   * that bound, so the chart is always laid out at a real size (including inside
   * a carousel slide that is translated off-screen).
   */
  height: number;
  /**
   * Render prop receiving the chart's measured width, so the chart can thin its
   * own axis ticks to its real container size (see utils/chart `yearTicks`).
   * Must return a single Recharts chart element for ResponsiveContainer.
   */
  children: (width: number) => React.ReactElement;
}

export const ResponsiveChart: React.FC<ResponsiveChartProps> = ({ height, children }) => {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  return (
    <div ref={ref} style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        {children(width)}
      </ResponsiveContainer>
    </div>
  );
};

export default ResponsiveChart;
