import type { Metadata } from "next";
import Link from "next/link";
import LearnPage, { Caveat, Formula, InApp } from "@/components/LearnPage";

export const metadata: Metadata = {
  title: "Monte Carlo simulation · Sector Insight",
  description:
    "How Monte Carlo simulation of geometric Brownian motion produces a distribution of portfolio outcomes rather than a single number.",
};

export default function Page() {
  return (
    <LearnPage slug="monte-carlo">
      <h2>The question it answers</h2>
      <p>
        <strong>What is the range?</strong> The other two models solve equations
        to get a single expected value and a single volatility. Monte Carlo does
        something cruder and, in some ways, more honest: it plays the next ten
        years forward ten thousand times and shows you the whole spread of what
        happened.
      </p>

      <h2>The idea</h2>
      <p>
        The method is named after the casino, and the logic is the logic of a
        casino: if you cannot derive the odds analytically, deal the hand enough
        times and count. Rather than asking &ldquo;what is the formula for the
        5th-percentile outcome,&rdquo; you generate thousands of possible futures
        by drawing random shocks, and then simply look at where the 5th
        percentile of those futures landed.
      </p>
      <p>
        This buys you something the parametric models cannot easily give: a path.
        Each simulation is a month-by-month trajectory, not just an endpoint. That
        is what makes <strong>maximum drawdown</strong> — the worst peak-to-trough
        fall along the way — computable at all. Two portfolios can end at the same
        value having taken wildly different routes there, and the route is what
        determines whether you would actually have held on.
      </p>

      <h2>The model being simulated</h2>
      <p>
        Portfolio value is assumed to follow <strong>geometric Brownian
        motion</strong> — the same process underlying the Black-Scholes option
        model. In words: returns compound continuously, and each period&rsquo;s
        return is random with a constant average drift and constant volatility.
      </p>
      <Formula note="V₀ initial value · μ drift · σ volatility · T years · Z a standard normal draw">
        V = V₀ · exp((μ − ½σ²)T + σ√T · Z)
      </Formula>
      <p>
        The <code>−½σ²</code> term is the part people miss and it matters a great
        deal. Volatility drags compound growth down: a portfolio that gains 50%
        then loses 50% is not flat, it is down 25%. Two portfolios with identical
        average returns will not end in the same place if one is more volatile —
        the volatile one ends lower. This is the mathematical statement of why
        risk costs you money even when the average looks fine.
      </p>

      <h2>Reading the distribution</h2>
      <p>
        The output is a set of percentiles of terminal value. They are not
        predictions; they are a description of the spread the model implies.
      </p>
      <ul>
        <li>
          <strong>p50 (median)</strong> — half the simulations ended above this,
          half below. Note that it sits <em>below</em> the mean, because
          compounding makes the distribution right-skewed: the upside is
          unbounded, the downside stops at zero.
        </li>
        <li>
          <strong>p5 and p95</strong> — a rough 90% range. The gap between them
          is the honest picture of how little anyone knows about a ten-year
          outcome.
        </li>
        <li>
          <strong>Maximum drawdown</strong> — the median worst peak-to-trough
          decline along the path. Usually the single most behaviourally relevant
          number on the screen.
        </li>
        <li>
          <strong>Probability of loss / of doubling</strong> — the share of
          simulations finishing below the starting value, or at twice it.
        </li>
      </ul>

      <h2>Why the Monte Carlo column starts out badged</h2>
      <p>
        Simulation is the only genuinely expensive computation in the app.
        Rather than make you wait for it, the engine runs a small batch of paths
        first and publishes a <strong>provisional</strong> result inside the
        half-second budget, then continues simulating in the background and
        replaces the numbers in place when the full run completes.
      </p>
      <p>
        The provisional badge is not decoration — a small sample genuinely has
        sampling error, and the tail statistics (p5, VaR, CVaR) are the ones that
        move most as more paths arrive, because they depend on the rarest draws.
        The assumptions panel reports a{" "}
        <strong>convergence standard error</strong> so you can see how much
        wobble remains in the estimate.
      </p>

      <Caveat>
        <p>
          <strong>Randomness is not the same as uncertainty.</strong> This is the
          deepest limitation. The simulation explores variation <em>within</em> a
          model whose μ and σ are assumed known and constant. It does not explore
          the possibility that μ and σ are simply wrong — which is where most
          real-world loss comes from. Ten thousand paths look authoritative and
          quantify only one of the two uncertainties.
        </p>
        <p>
          <strong>GBM has thin tails.</strong> Normal draws underestimate how
          often extreme moves actually occur. Real markets produce
          &ldquo;impossible&rdquo; days regularly, so the p5 outcome here is
          likely optimistic about how bad bad gets.
        </p>
        <p>
          <strong>Constant volatility is false.</strong> Real volatility clusters
          — calm follows calm, chaos follows chaos. GBM assumes it never changes,
          which understates the risk of a sustained bad stretch.
        </p>
        <p>
          <strong>No path dependence in your behaviour.</strong> The simulation
          assumes you hold through everything. The drawdown number exists
          precisely to make you ask whether you actually would.
        </p>
      </Caveat>

      <InApp>
        <p>
          The engine simulates the portfolio&rsquo;s own drift{" "}
          <code>w · μ</code> and volatility <code>√(wᵀΣw)</code> with monthly
          steps, so a genuine path exists for the drawdown statistic. It runs in
          a process pool to keep the API responsive, defaults to 10,000
          simulations, and reports <code>empirical_simulated</code> as its
          estimation method.
        </p>
        <p>
          The random number generator is <strong>seeded from the request</strong>,
          so an identical request against an identical snapshot reproduces
          bit-identical results. That is what makes the results cacheable, makes
          a comparison from last month reopenable, and means you are never shown
          a different answer to the same question.
        </p>
        <p>
          Because it simulates the same GBM the parametric models assume, its
          numbers converge to theirs as the simulation count grows — a property
          the test suite actually verifies. Where they differ at 10,000 paths,
          the difference is sampling error, not disagreement.{" "}
          <Link href="/learn/why-models-disagree">
            Real disagreement comes from elsewhere
          </Link>
          .
        </p>
      </InApp>
    </LearnPage>
  );
}
