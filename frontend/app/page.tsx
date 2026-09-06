"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { LEARN_PAGES } from "@/lib/learn";

export default function Home() {
  const { me, loading } = useAuth();
  const foundations = LEARN_PAGES.filter((p) => p.group === "foundations");

  return (
    <div className="container stack">
      <div className="card">
        <h1>Three risk models. One portfolio. See why they disagree.</h1>
        <p className="muted">
          Sector Insight puts a Fama-French factor model, Black-Litterman, and
          Monte Carlo simulation side by side against the same portfolio, the
          same data, and the same assumptions — and lets the differences teach.
          The unit of advice is the <strong>sector</strong>, not the trade.
        </p>
        <div className="row" style={{ marginTop: "1rem" }}>
          {loading ? null : me ? (
            <>
              <Link href="/compare" className="btn primary">
                Run a comparison
              </Link>
              <Link href="/portfolios" className="btn">
                Manage portfolios
              </Link>
            </>
          ) : (
            <>
              <Link href="/register" className="btn primary">
                Get started
              </Link>
              <Link href="/login" className="btn">
                Log in
              </Link>
            </>
          )}
          <Link href="/learn" className="btn">
            Learn how the models work
          </Link>
        </div>
      </div>

      <h2 style={{ marginTop: "1.5rem" }}>The three models</h2>
      <div className="model-cols">
        <ModelTeaser
          slug="fama-french"
          name="Fama-French"
          accent="var(--ff)"
          style="Factor regression"
          answers="What drives risk?"
        />
        <ModelTeaser
          slug="black-litterman"
          name="Black-Litterman"
          accent="var(--bl)"
          style="Equilibrium + views"
          answers="What should shift?"
        />
        <ModelTeaser
          slug="monte-carlo"
          name="Monte Carlo"
          accent="var(--mc)"
          style="Simulation"
          answers="What's the range?"
        />
      </div>

      <h2 style={{ marginTop: "1.5rem" }}>Background reading</h2>
      <div className="learn-grid">
        {foundations.map((p) => (
          <Link
            key={p.slug}
            href={`/learn/${p.slug}`}
            className="learn-card"
            style={{ ["--accent" as string]: p.accent }}
          >
            <span className="learn-kicker">{p.kicker}</span>
            <span className="learn-card-title">{p.title}</span>
            <span className="muted small">{p.blurb}</span>
            <span className="learn-card-cta">Read →</span>
          </Link>
        ))}
      </div>
    </div>
  );
}

function ModelTeaser({
  slug,
  name,
  accent,
  style,
  answers,
}: {
  slug: string;
  name: string;
  accent: string;
  style: string;
  answers: string;
}) {
  return (
    <Link
      href={`/learn/${slug}`}
      className="model-col model-col-link"
      style={{ ["--accent" as string]: accent }}
    >
      <div className="head">
        <span className="name">{name}</span>
      </div>
      <div className="metric-row">
        <span className="k">Style</span>
        <span>{style}</span>
      </div>
      <div className="metric-row">
        <span className="k">Answers</span>
        <span>{answers}</span>
      </div>
      <div className="metric-row">
        <span className="k">Learn</span>
        <span className="learn-card-cta">How it works →</span>
      </div>
    </Link>
  );
}
