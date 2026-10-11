// A single before -> after metric row. Shared by the three-column
// SuggestedShifts panel and the single-model EasyMoves view so the two never
// drift on how an improvement is coloured.
export default function Delta({
  k,
  before,
  after,
  good,
}: {
  k: string;
  before: string;
  after: string;
  good: boolean;
}) {
  return (
    <div className="metric-row small" style={{ padding: "0.15rem 0", border: 0 }}>
      <span className="k">{k}</span>
      <span>
        <span className="muted">{before}</span> →{" "}
        <span className={before === after ? undefined : good ? "gain" : "loss"}>
          {after}
        </span>
      </span>
    </div>
  );
}
