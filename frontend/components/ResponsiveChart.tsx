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
  // Mount Recharts' ResponsiveContainer only ONCE we've measured a real width.
  // The wrapper div is always laid out at the bounded `height`, so this reserves
  // the space (no layout shift) but defers the chart until the container has a
  // size — which avoids Recharts' transient "width(-1)/height(-1)" console
  // warning for a chart that first renders inside an off-screen carousel slide.
  return (
    <div ref={ref} style={{ width: '100%', height }}>
      {width > 0 && (
        <ResponsiveContainer width={width} height={height}>
          {children(width)}
        </ResponsiveContainer>
      )}
    </div>
  );
};

export default ResponsiveChart;
