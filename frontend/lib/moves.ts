// Plain-language explanation of a sector shift, assembled from the numbers the
// model already reported. No math of its own: every figure here comes off the
// SectorShift, so the prose cannot disagree with the deltas rendered beside it.
//
// Three rules this copy keeps, and why:
//   - it never says buy, sell, hold or trade — the unit of advice is the sector
//     (PRD §3 non-goal), and the same convention already governs
//     components/SuggestedShifts.tsx;
//   - it leads with whatever the chosen risk level actually ranks by, because
//     that is why *this* shift sits in *this* slot (engines/common/shifts.py);
//   - it always names the other side of the trade-off, so no card hides a cost.
//
// Direction is read off the raw delta but described against the *rendered*
// figures. A shift can genuinely lower volatility by less than the displayed
// precision, and "falls from 16.3% to 16.3%" reads as a bug even when the
// underlying claim is true.

import type { CommonMetrics, ModelId, RiskLevel, SectorShift } from "./types";
import { MODEL_LABEL } from "./types";
import { num, pct } from "./format";

const EPS = 1e-9;
const ORDINAL = ["first", "second", "third"];

export function moveHeadline(shift: SectorShift): string {
  return `Shift ${pct(shift.fraction, 0)} of the portfolio from ${
    shift.from_sector
  } to ${shift.to_sector}`;
}

export interface MoveDigits {
  sharpe: number;
  vol: number;
  ret: number;
}

/** Display precision for a whole list of moves, widened by one digit only where
 *  the default would mislead. Decided once per list so the columns line up.
 *
 *  Two things mislead. A figure that renders "16.3% → 16.3%" looks like a bug
 *  even when the move is real, so any figure whose own before/after collapses
 *  gets widened. And a *ranking key* that reads the same for every move makes
 *  the order look arbitrary — so ties widen the key, and only the key, since
 *  the risk level decides which figure that is (engines/common/shifts.py:
 *  volatility for conservative, Sharpe for moderate, return for aggressive).
 *  Ties on a figure nobody is ranked by are just ties, and chasing them adds
 *  false precision. */
export function moveDigits(
  shifts: SectorShift[],
  riskLevel: RiskLevel,
): MoveDigits {
  return {
    sharpe: widen(shifts, (m) => m.sharpe_ratio, num, 2, riskLevel === "moderate"),
    vol: widen(shifts, (m) => m.volatility, pct, 1, riskLevel === "conservative"),
    ret: widen(shifts, (m) => m.expected_return, pct, 1, riskLevel === "aggressive"),
  };
}

function widen(
  shifts: SectorShift[],
  pick: (m: CommonMetrics) => number,
  fmt: (x: number, digits: number) => string,
  base: number,
  isRankingKey: boolean,
): number {
  const hidesAChange = shifts.some(
    (s) => fmt(pick(s.metrics_before), base) === fmt(pick(s.metrics_after), base),
  );
  const afters = shifts.map((s) => fmt(pick(s.metrics_after), base));
  const hidesTheOrder = isRankingKey && new Set(afters).size !== afters.length;
  return hidesAChange || hidesTheOrder ? base + 1 : base;
}

const DEFAULT_DIGITS: MoveDigits = { sharpe: 2, vol: 1, ret: 1 };

export function describeMove(
  shift: SectorShift,
  model: ModelId,
  riskLevel: RiskLevel,
  rank = 0,
  digits: MoveDigits = DEFAULT_DIGITS,
): string {
  const b = shift.metrics_before;
  const a = shift.metrics_after;
  const label = MODEL_LABEL[model];
  const ordinal = ORDINAL[rank] ?? `${rank + 1}th`;
  const dRet = a.expected_return - b.expected_return;

  const volBefore = pct(b.volatility, digits.vol);
  const volAfter = pct(a.volatility, digits.vol);
  const retBefore = pct(b.expected_return, digits.ret);
  const retAfter = pct(a.expected_return, digits.ret);
  const volMoved = volBefore !== volAfter;
  const retMoved = retBefore !== retAfter;

  const vol = move("volatility", a.volatility - b.volatility, volBefore, volAfter);
  const ret = move("expected return", dRet, retBefore, retAfter);
  const sharpe = move(
    "return per unit of risk",
    a.sharpe_ratio - b.sharpe_ratio,
    num(b.sharpe_ratio, digits.sharpe),
    num(a.sharpe_ratio, digits.sharpe),
  );

  if (riskLevel === "conservative") {
    // Every shift at this level lowers volatility — occasionally by less than
    // the displayed precision, where "takes risk out: volatility unchanged"
    // would read as a contradiction.
    const lead = volMoved
      ? `because of how much risk it takes out: ${vol}`
      : "because it still lowers volatility, though only slightly";
    return (
      `${label} puts this ${ordinal} ${lead}, and ${sharpe}. ` +
      cost(dRet, ret, retMoved)
    );
  }
  if (riskLevel === "aggressive") {
    // The measure is named in the clause before, so the figures refer back to
    // it rather than repeating "expected return". A shift can qualify here with
    // a *falling* return (a big volatility cut can carry the Sharpe gain), so
    // the direction is still read off the delta.
    return (
      `${label} puts this ${ordinal} on expected return: ` +
      `${move("it", dRet, retBefore, retAfter)}, and ${sharpe}. ` +
      (a.volatility - b.volatility > EPS
        ? `You take on more risk for it — ${vol}.`
        : `${capitalize(vol)}, so it costs you nothing in risk.`)
    );
  }
  // Moderate ranks by Sharpe gain. Naming the measure and then repeating it in
  // full ("…on return per unit of risk: return per unit of risk rises from…")
  // reads badly, so name it once and then give just the figures.
  const before = num(b.sharpe_ratio, digits.sharpe);
  const after = num(a.sharpe_ratio, digits.sharpe);
  const lift =
    before === after
      ? "by less than the displayed precision"
      : `from ${before} to ${after}`;
  return (
    `${label} ranks this ${ordinal} on return per unit of risk, lifting it ` +
    `${lift}, while ${vol}. ${cost(dRet, ret, retMoved)}`
  );
}

/** "volatility falls from 14.1% to 13.6%", or "volatility is effectively
 *  unchanged at 14.1%" when the move is real but smaller than one displayed
 *  digit. Direction is never assumed: a Sharpe-improving shift can move either
 *  way on both volatility and return. */
function move(
  what: string,
  delta: number,
  before: string,
  after: string,
): string {
  if (before === after) return `${what} is effectively unchanged at ${before}`;
  if (delta < -EPS) return `${what} falls from ${before} to ${after}`;
  if (delta > EPS) return `${what} rises from ${before} to ${after}`;
  return `${what} stays at ${before}`;
}

/** The other side of the trade-off. When the return moved by less than the
 *  displayed precision there is no trade-off to announce — "the trade-off is on
 *  the other side: expected return is effectively unchanged" contradicts
 *  itself, and so does tacking ", too" onto it. */
function cost(dRet: number, ret: string, moved: boolean): string {
  if (!moved) return `${capitalize(ret)}.`;
  if (dRet < -EPS) return `The trade-off is on the other side: ${ret}.`;
  if (dRet > EPS) return `${capitalize(ret)}, too.`;
  return `${capitalize(ret)}.`;
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
