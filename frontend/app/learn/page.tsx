import type { Metadata } from "next";
import Link from "next/link";
import { LEARN_PAGES } from "@/lib/learn";

export const metadata: Metadata = {
  title: "Learn · Sector Insight",
  description:
    "Plain-language explanations of the Fama-French, Black-Litterman and Monte Carlo models, sector investing, and how to read the numbers.",
};

export default function LearnIndex() {
  const models = LEARN_PAGES.filter((p) => p.group === "models");
  const foundations = LEARN_PAGES.filter((p) => p.group === "foundations");

  return (
    <div className="container stack">
      <div className="card">
        <h1>Learn</h1>
        <p className="muted">
          Sector Insight shows you three risk models at once. These pages explain
          what each model is, what question it is built to answer, and where it
          stops being trustworthy — so the numbers on the comparison screen mean
          something rather than just appearing.
        </p>
        <p className="muted small">
          No prior finance coursework assumed. Formulas are shown, but every one
          is explained in words first.
        </p>
      </div>

      <h2 style={{ marginTop: "1.5rem" }}>Start here</h2>
      <div className="learn-grid">
        {foundations
          .filter((p) => p.slug === "sector-investing")
          .map((p) => (
            <LearnCard key={p.slug} slug={p.slug} />
          ))}
      </div>

      <h2 style={{ marginTop: "1.5rem" }}>The three models</h2>
      <div className="learn-grid">
        {models.map((p) => (
          <LearnCard key={p.slug} slug={p.slug} />
        ))}
      </div>

      <h2 style={{ marginTop: "1.5rem" }}>Making sense of the output</h2>
      <div className="learn-grid">
        {foundations
          .filter((p) => p.slug !== "sector-investing")
          .map((p) => (
            <LearnCard key={p.slug} slug={p.slug} />
          ))}
      </div>
    </div>
  );
}

function LearnCard({ slug }: { slug: string }) {
  const p = LEARN_PAGES.find((e) => e.slug === slug)!;
  return (
    <Link
      href={`/learn/${p.slug}`}
      className="learn-card"
      style={{ ["--accent" as string]: p.accent }}
    >
      <span className="learn-kicker">{p.kicker}</span>
      <span className="learn-card-title">{p.title}</span>
      <span className="muted small">{p.blurb}</span>
      <span className="learn-card-cta">Read →</span>
    </Link>
  );
}
