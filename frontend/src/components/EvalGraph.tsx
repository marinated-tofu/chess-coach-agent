import { useMemo } from 'react';
import { Area, AreaChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { formatEvalValue, moveLabel, winPctAtPly, type ReviewMove } from '../lib/reviewApi';
import type { MoveClassification } from '../lib/types';
import { GRAPH_MARKED, MOVE_LABELS } from './moveLabels';

type Point = {
  ply: number;
  win: number | null;
  label: MoveClassification | null;
  move: ReviewMove | null;
};

const PLOT_BLACK = '#33383c';
const PLOT_WHITE = '#f3f2ee';
const CURRENT = '#1f8fe5';

function describe(move: ReviewMove | null, win: number | null): string {
  if (!move) return 'Start position';
  const label = move.classification ? `, ${MOVE_LABELS[move.classification].name.toLowerCase()}` : '';
  const evalText = formatEvalValue(move.eval_cp, move.eval_mate, move.color);
  return `${moveLabel(move)} ${move.san}${label}, ${evalText}${win != null ? `, White ${Math.round(win)}%` : ''}`;
}

function GraphTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: Point }> }) {
  const point = active ? payload?.[0]?.payload : undefined;
  if (!point) return null;
  const move = point.move;
  return (
    <div className="eval-graph-tip">
      <strong>{move ? `${moveLabel(move)} ${move.san}` : 'Start'}</strong>
      {point.label && (
        <span className="eval-graph-tip-label">
          <i style={{ backgroundColor: MOVE_LABELS[point.label].color }} aria-hidden="true" />
          {MOVE_LABELS[point.label].name}
        </span>
      )}
      <span className="tnum">
        {move ? formatEvalValue(move.eval_cp, move.eval_mate, move.color) : '0.0'}
        {point.win != null ? ` · White ${Math.round(point.win)}%` : ''}
      </span>
    </div>
  );
}

/**
 * Win chance over the game: the light area is White's share, the dark band above it is Black's.
 * Click a point to jump there. As a slider it reports the current ply; the arrow keys handled
 * by the review page move it.
 */
export function EvalGraph({
  moves,
  currentPly,
  onSelectPly,
  playerColor
}: {
  moves: ReviewMove[];
  currentPly: number;
  onSelectPly: (ply: number) => void;
  playerColor: 'white' | 'black' | null;
}) {
  const data = useMemo<Point[]>(
    () => [
      { ply: 0, win: 50, label: null, move: null },
      ...moves.map((move, index) => ({
        ply: index + 1,
        win: winPctAtPly(moves, index + 1),
        label: move.classification ?? null,
        move
      }))
    ],
    [moves]
  );

  const summary = useMemo(() => {
    const marked = moves.filter((move) => move.classification && ['mistake', 'blunder', 'miss'].includes(move.classification));
    let swing = { drop: 0, move: null as ReviewMove | null };
    for (const move of moves) {
      if ((move.win_pct_loss ?? 0) > swing.drop) swing = { drop: move.win_pct_loss ?? 0, move };
    }
    const final = data[data.length - 1]?.win;
    const parts = [`Win chance graph over ${moves.length} plies.`];
    if (final != null) parts.push(`Ends at White ${Math.round(final)}%.`);
    if (swing.move) parts.push(`Biggest swing: ${moveLabel(swing.move)} ${swing.move.san}, ${Math.round(swing.drop)} points.`);
    parts.push(`${marked.length} mistakes, misses or blunders marked.`);
    return parts.join(' ');
  }, [data, moves]);

  const current = data[Math.max(0, Math.min(currentPly, data.length - 1))];

  return (
    <div
      className="eval-graph"
      role="slider"
      tabIndex={0}
      aria-label={summary}
      aria-valuemin={0}
      aria-valuemax={moves.length}
      aria-valuenow={current?.ply ?? 0}
      aria-valuetext={describe(current?.move ?? null, current?.win ?? null)}
      data-player={playerColor ?? undefined}
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={data}
          margin={{ top: 0, right: 0, bottom: 0, left: 0 }}
          onClick={(state) => {
            const index = state?.activeTooltipIndex;
            if (index == null) return;
            const point = data[Number(index)];
            if (point) onSelectPly(point.ply);
          }}
        >
          <XAxis dataKey="ply" type="number" domain={[0, Math.max(1, moves.length)]} hide />
          <YAxis domain={[0, 100]} hide />
          <ReferenceLine y={50} stroke="#8b9399" strokeDasharray="3 3" strokeWidth={1} ifOverflow="hidden" />
          {current && <ReferenceLine x={current.ply} stroke={CURRENT} strokeWidth={2} ifOverflow="hidden" />}
          <Tooltip
            content={<GraphTooltip />}
            cursor={{ stroke: '#c7ccd1', strokeWidth: 1 }}
            isAnimationActive={false}
          />
          <Area
            type="linear"
            dataKey="win"
            baseValue={0}
            stroke="#c9cdd1"
            strokeWidth={1}
            fill={PLOT_WHITE}
            fillOpacity={1}
            connectNulls
            isAnimationActive={false}
            activeDot={{ r: 4, fill: CURRENT, stroke: PLOT_BLACK, strokeWidth: 2 }}
            dot={(props: { cx?: number; cy?: number; index?: number; payload?: Point }) => {
              const { cx, cy, payload, index } = props;
              const key = `dot-${index}`;
              if (cx == null || cy == null || !payload?.label || !GRAPH_MARKED.has(payload.label)) return <g key={key} />;
              return (
                <circle
                  key={key}
                  cx={cx}
                  cy={cy}
                  r={4}
                  fill={MOVE_LABELS[payload.label].color}
                  stroke={payload.ply === currentPly ? CURRENT : '#ffffff'}
                  strokeWidth={2}
                />
              );
            }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
