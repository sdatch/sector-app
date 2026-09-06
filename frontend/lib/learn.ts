// Registry for the /learn section. One entry per content page — the index,
// the nav, and each page's prev/next footer all read from here, so adding a
// page means adding a route + one row below.

export interface LearnEntry {
  slug: string;
  title: string;
  kicker: string;
  blurb: string;
  /** CSS custom-property expression for the page accent. */
  accent: string;
  group: "models" | "foundations";
}

export const LEARN_PAGES: LearnEntry[] = [
  {
    slug: "sector-investing",
    title: "Sector investing",
    kicker: "The strategy",
    blurb:
      "Why this tool advises at the level of the sector rather than the trade, and what a sector tilt actually does to a portfolio.",
    accent: "var(--primary)",
    group: "foundations",
  },
  {
    slug: "fama-french",
    title: "Fama-French 5-factor",
    kicker: "Model 1 · factor regression",
    blurb:
      "Decomposes returns into five systematic factors. Answers: what is actually driving my risk?",
    accent: "var(--ff)",
    group: "models",
  },
  {
    slug: "black-litterman",
    title: "Black-Litterman",
    kicker: "Model 2 · equilibrium + views",
    blurb:
      "Starts from what the market already believes, then bends it toward your views. Answers: what should shift?",
    accent: "var(--bl)",
    group: "models",
  },
  {
    slug: "monte-carlo",
    title: "Monte Carlo simulation",
    kicker: "Model 3 · simulation",
    blurb:
      "Simulates thousands of possible futures instead of solving for one. Answers: what is the range of outcomes?",
    accent: "var(--mc)",
    group: "models",
  },
  {
    slug: "reading-the-numbers",
    title: "Reading the numbers",
    kicker: "The metrics",
    blurb:
      "Volatility, VaR, CVaR, Sharpe, drawdown and sector attribution — what each one means and where it can mislead.",
    accent: "var(--primary)",
    group: "foundations",
  },
  {
    slug: "why-models-disagree",
    title: "Why models disagree",
    kicker: "The point of the tool",
    blurb:
      "Three respectable models, identical inputs, different answers. The disagreement is the lesson, not a bug.",
    accent: "var(--primary)",
    group: "foundations",
  },
];

export function learnEntry(slug: string): LearnEntry | undefined {
  return LEARN_PAGES.find((p) => p.slug === slug);
}

export function learnNeighbors(slug: string): {
  prev?: LearnEntry;
  next?: LearnEntry;
} {
  const i = LEARN_PAGES.findIndex((p) => p.slug === slug);
  if (i < 0) return {};
  return { prev: LEARN_PAGES[i - 1], next: LEARN_PAGES[i + 1] };
}
