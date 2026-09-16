import type { Metadata } from "next";
import Link from "next/link";
import LearnPage, { Caveat, InApp } from "@/components/LearnPage";

export const metadata: Metadata = {
  title: "Why models disagree · Sector Insight",
  description:
    "Three respectable risk models given identical inputs produce different answers. What the disagreement means and how to use it.",
};

export default function Page() {
  return (
    <LearnPage slug="why-models-disagree">
      <h2>The disagreement is the product</h2>
      <p>
        Most tools show you one risk number. The number looks objective, and
        almost nobody is told that it depends entirely on the model that produced
        it. Change the model and the number changes — sometimes by a lot — even
        though the portfolio, the data and the market did not change at all.
      </p>
      <p>
        Sector Insight runs three models against the same portfolio, the same
        snapshot, and the same assumptions, and puts the answers next to each
        other. Where they agree, you can hold the conclusion with some
        confidence. Where they diverge, you have learned something specific about
        which assumption is doing the work.
      </p>

      <h2>What has been held constant</h2>
      <p>
        For the comparison to mean anything, the differences have to come from
        the models and nothing else. Four things are pinned:
      </p>
      <ul>
        <li>
          <strong>The same data snapshot.</strong> All three read one immutable
          daily artifact. No model gets fresher prices than another.
        </li>
        <li>
          <strong>The same allocation.</strong> One set of sector weights,
          derived once from your positions and snapshot prices.
        </li>
        <li>
          <strong>The same request scope.</strong> Identical horizon, confidence
          level and starting value.
        </li>
        <li>
          <strong>The same output conventions.</strong> One shared module turns
          raw model output into every displayed metric — horizon scaling, VaR
          sign convention, Euler attribution. No engine defines its own.
        </li>
      </ul>
      <p>
        That last one matters more than it sounds. A large share of apparent
        disagreement between risk systems in the real world is not modeling
        disagreement at all — it is one system annualizing differently or
        reporting VaR with the opposite sign. Removing that noise is what leaves
        the genuine differences visible.
      </p>

      <h2>Where the real differences come from</h2>

      <h3>1. Different sources of expected return</h3>
      <p>
        Fama-French derives expected returns from{" "}
        <strong>factor exposures and their historical premia</strong> — a
        backward-looking, statistical answer. Black-Litterman derives them from{" "}
        <strong>what the market&rsquo;s current allocation implies</strong>,
        adjusted by your views — a forward-looking, equilibrium answer. These are
        genuinely different philosophies, and when they disagree it usually means
        the market is currently pricing a sector differently from how its
        historical factor behaviour would suggest. That gap is worth
        investigating.
      </p>

      <h3>2. Parametric versus empirical tails</h3>
      <p>
        Fama-French and Black-Litterman compute VaR and CVaR in closed form from
        a lognormal assumption. Monte Carlo reads them off ten thousand simulated
        outcomes. Even simulating the <em>exact same</em> process, the empirical
        tail carries sampling error — and the rarer the quantile, the fewer
        observations behind it. This is the most common source of a modest gap in
        the loss numbers, and it shrinks as simulation count rises.
      </p>

      <h3>3. Views entering only one model</h3>
      <p>
        Views are consumed by Black-Litterman alone. If you tell the app you
        expect Energy to return 8%, the BL column moves and the other two do not.
        This is correct behaviour, not an inconsistency — and it isolates
        precisely how much of the answer is coming from your opinion rather than
        from the data. If BL swings dramatically on a view you would struggle to
        defend, that is worth knowing before you act on it.
      </p>

      <h3>4. Path versus endpoint</h3>
      <p>
        Only Monte Carlo simulates the journey, so only Monte Carlo can report
        maximum drawdown. Two portfolios can share an expected return, a
        volatility and a terminal distribution while offering completely
        different experiences along the way.
      </p>

      <h3>5. Different suggested shifts</h3>
      <p>
        Under each model the app shows up to three sector shifts to explore,
        such as &ldquo;move 10% from Financials to Real Estate.&rdquo; All three
        models search the <em>same</em> candidates: every sector you hold
        moving 5% or 10% of the portfolio into any other sector. Each model ranks those
        candidates using its own expected returns and covariance, so the lists
        often differ. A shift that appears for all three models holds up
        whichever model you trust. A shift that appears for only one model
        rests on that model&rsquo;s assumptions.
      </p>
      <p>
        Every shift shown must raise the Sharpe ratio. The risk level you pick
        decides what else a shift must do and which shifts come first.
        Conservative shifts must lower volatility and are ranked by how much
        they lower it. Moderate shifts may not raise volatility and are ranked
        by Sharpe gain. Aggressive shifts may raise volatility by up to 10% and
        are ranked by how much they add to expected return. Monte Carlo does
        not run a separate simulation for each shift. It estimates shift
        numbers in closed form from the same inputs it simulates from, and
        labels them as estimates.
      </p>

      <h2>How to actually use the comparison</h2>
      <ul>
        <li>
          <strong>Look for agreement first.</strong> If all three say your risk
          is concentrated in two sectors, that finding is robust to modeling
          choices and you can act on it.
        </li>
        <li>
          <strong>Treat the spread as the real error bar.</strong> If expected
          return ranges from 6% to 9% across the columns, the honest reading is
          &ldquo;somewhere around seven, and nobody knows&rdquo; — not the number
          you liked best.
        </li>
        <li>
          <strong>Ask what a divergence is made of.</strong> A big gap between
          the parametric and simulated loss numbers points at tail assumptions. A
          big gap between FF and BL expected returns points at history versus
          market pricing.
        </li>
        <li>
          <strong>Do not shop for the friendliest column.</strong> Picking the
          model that flatters the portfolio you already hold is the single most
          common way to misuse a tool like this.
        </li>
        <li>
          <strong>Change one thing and re-run.</strong> The models are most
          instructive in motion. Shift a weight by five points, extend the
          horizon, add a view — and watch which column responds most.
        </li>
      </ul>

      <h2>When one column fails</h2>
      <p>
        A model failing is treated as information, not an error page. If
        Black-Litterman cannot process a view naming an unknown sector, that
        column reports the failure with a plain-language reason and the other two
        still render. You are never left with a blank screen because one engine
        objected to one input.
      </p>

      <Caveat>
        <p>
          Three models agreeing does <strong>not</strong> mean they are right.
          They share a data snapshot, a sector classification, a covariance
          matrix, and an assumption that returns are approximately lognormal with
          stable parameters. If that shared foundation is wrong — as it
          conspicuously is during a crisis — all three will be wrong together and
          confidently.
        </p>
        <p>
          Agreement narrows model risk. It does nothing about the risk that the
          world stops behaving the way the data did.
        </p>
      </Caveat>

      <InApp>
        <p>
          Adding a fourth model would require implementing one protocol and
          registering it. Nothing in the orchestration or API layer names a model
          — it consumes a uniform stream of outcome transitions — which is what
          keeps the comparison genuinely apples-to-apples rather than three
          bespoke reports pasted side by side.
        </p>
        <p>
          Start from{" "}
          <Link href="/learn/sector-investing">why sectors are the unit</Link>, or
          go run a comparison and see it happen.
        </p>
      </InApp>
    </LearnPage>
  );
}
