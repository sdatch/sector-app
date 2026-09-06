import Link from "next/link";
import { learnEntry, learnNeighbors } from "@/lib/learn";

/**
 * Shared chrome for a /learn content page: accent header, prose body, and a
 * prev/next footer driven by the LEARN_PAGES order.
 */
export default function LearnPage({
  slug,
  children,
}: {
  slug: string;
  children: React.ReactNode;
}) {
  const entry = learnEntry(slug);
  const { prev, next } = learnNeighbors(slug);
  if (!entry) return null;

  return (
    <div className="container stack">
      <Link href="/learn" className="small muted">
        ← All topics
      </Link>

      <article
        className="card learn"
        style={{ ["--accent" as string]: entry.accent }}
      >
        <div className="learn-head">
          <span className="learn-kicker">{entry.kicker}</span>
          <h1>{entry.title}</h1>
          <p className="muted learn-lede">{entry.blurb}</p>
        </div>
        {children}
      </article>

      <nav className="learn-nav">
        {prev ? (
          <Link href={`/learn/${prev.slug}`} className="learn-nav-link">
            <span className="muted small">← Previous</span>
            <span>{prev.title}</span>
          </Link>
        ) : (
          <span />
        )}
        {next ? (
          <Link
            href={`/learn/${next.slug}`}
            className="learn-nav-link align-right"
          >
            <span className="muted small">Next →</span>
            <span>{next.title}</span>
          </Link>
        ) : (
          <span />
        )}
      </nav>
    </div>
  );
}

/** A labelled formula block — kept visually distinct from prose. */
export function Formula({
  children,
  note,
}: {
  children: React.ReactNode;
  note?: string;
}) {
  return (
    <div className="formula">
      <code>{children}</code>
      {note && <span className="muted small">{note}</span>}
    </div>
  );
}

/** Callout for the "what this model cannot tell you" sections. */
export function Caveat({ children }: { children: React.ReactNode }) {
  return (
    <div className="learn-caveat">
      <strong>Where it breaks down</strong>
      <div>{children}</div>
    </div>
  );
}

/** "As implemented here" — ties the theory to this app's actual settings. */
export function InApp({ children }: { children: React.ReactNode }) {
  return (
    <div className="learn-inapp">
      <strong>As implemented in Sector Insight</strong>
      <div>{children}</div>
    </div>
  );
}
