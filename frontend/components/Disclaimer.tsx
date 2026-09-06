import { DISCLAIMER_FULL, DISCLAIMER_SHORT } from "@/lib/types";

export function DisclaimerFooter() {
  return (
    <footer className="disclaimer" title={DISCLAIMER_FULL}>
      <strong>Educational tool — not financial advice.</strong>{" "}
      {DISCLAIMER_SHORT.replace("Educational tool — not financial advice. ", "")}
    </footer>
  );
}

export function DisclaimerInline() {
  // Rendered on every comparison view (PRD FR-7).
  return <div className="disclaimer-inline">{DISCLAIMER_SHORT}</div>;
}
