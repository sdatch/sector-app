import type { Metadata } from "next";
import Link from "next/link";
import LearnPage, { Caveat, Formula, InApp } from "@/components/LearnPage";

export const metadata: Metadata = {
  title: "Black-Litterman · Sector Insight",
  description:
    "How the Black-Litterman model blends market equilibrium with your own views to produce a suggested allocation.",
};

export default function Page() {
  return (
    <LearnPage slug="black-litterman">
      <h2>The question it answers</h2>
      <p>
        <strong>What should shift?</strong> Black-Litterman is the only one of
        the three models that produces an opinion about your allocation. It
        compares the mix you hold against the mix it thinks you should hold, and
        the difference is the <strong>advice delta</strong> on the comparison
        screen.
      </p>

      <h2>The problem it was built to solve</h2>
      <p>
        Classical mean-variance optimization — Markowitz, 1952 — is elegant and,
        used naively, close to unusable. You feed it expected returns and a
        covariance matrix, and it returns the portfolio with the best return per
        unit of risk. In practice it produces absurd answers: 90% in one sector,
        negative weights elsewhere, and a completely different allocation if you
        nudge one expected return by half a percent. It is an error-maximizer,
        because it aggressively exploits exactly the inputs you know least
        reliably.
      </p>
      <p>
        Fischer Black and Robert Litterman, at Goldman Sachs in 1990, fixed this
        by inverting the question. Instead of asking you to supply expected
        returns, they asked: <em>what expected returns would make the market
        portfolio optimal?</em> The market is the aggregate of every investor
        acting on their information; treat its allocation as the neutral answer
        and work backwards to the returns it implies.
      </p>

      <h2>Step one — the equilibrium prior</h2>
      <p>
        This backwards step is called <strong>reverse optimization</strong>.
        Given market-cap weights and the covariance matrix, the implied returns
        are:
      </p>
      <Formula note="δ is risk aversion; w_mkt are market-cap weights">
        Π = δ · Σ · w_mkt
      </Formula>
      <p>
        Read plainly: a sector deserves a higher expected return exactly to the
        extent that it contributes risk to the market portfolio. Nothing here is
        forecast — it is a restatement of what the market already holds. This is
        the <strong>prior</strong>, and it is a sane, stable starting point.
      </p>

      <h2>Step two — your views</h2>
      <p>
        A view is a statement like &ldquo;Energy will return 8% annually.&rdquo;
        What makes Black-Litterman genuinely useful is the second half: you also
        state <strong>how confident you are</strong>. The model then performs a
        Bayesian update, blending the equilibrium prior with your view in
        proportion to their relative certainty:
      </p>
      <Formula note="the Black-Litterman posterior">
        μ_BL = [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹ · [(τΣ)⁻¹Π + PᵀΩ⁻¹Q]
      </Formula>
      <p>
        That is dense, but the behaviour it produces is intuitive and worth
        internalizing:
      </p>
      <ul>
        <li>
          <strong>No views</strong> → the posterior equals the equilibrium, and
          the suggested weights are simply market weights. The model refuses to
          invent an opinion you did not give it.
        </li>
        <li>
          <strong>A low-confidence view</strong> → the allocation moves slightly
          in that direction.
        </li>
        <li>
          <strong>A high-confidence view</strong> → the allocation moves a lot.
        </li>
        <li>
          <strong>Correlations propagate the view.</strong> A view on Energy also
          nudges Materials, because the model knows they move together. You do
          not have to hold an opinion about every sector for the answer to be
          coherent across all of them.
        </li>
      </ul>
      <p>
        The suggested allocation is then the maximum-Sharpe portfolio under the
        posterior returns — the same optimization that misbehaved before, but now
        fed inputs anchored to equilibrium rather than to raw estimates, which is
        what tames it.
      </p>

      <h2>Reading the advice delta</h2>
      <p>
        The comparison screen shows your weight and the model&rsquo;s suggested
        weight side by side. Interpret the gap carefully:
      </p>
      <ul>
        <li>
          <strong>With no views entered</strong>, the delta is purely a statement
          of how far you sit from the market. That is useful information — it
          quantifies your active bet — but it is not a forecast that you are
          wrong.
        </li>
        <li>
          <strong>With views entered</strong>, the delta is the disciplined
          consequence of your own opinion. If it looks too aggressive, the honest
          response is usually that you overstated your confidence.
        </li>
        <li>
          <strong>It is not a trade list.</strong> It contains no view of your
          taxes, transaction costs, cost basis, or the rest of your financial
          life.
        </li>
      </ul>

      <Caveat>
        <p>
          <strong>Confidence is nearly impossible to calibrate.</strong> People
          are systematically overconfident about market forecasts, and the model
          faithfully amplifies whatever confidence you assert. Garbage in,
          rigorously-optimized garbage out.
        </p>
        <p>
          <strong>&ldquo;Equilibrium&rdquo; assumes the market is
          right.</strong> The prior is only neutral if you accept market-cap
          weights as sensible. During a bubble, the equilibrium prior is anchored
          to the bubble.
        </p>
        <p>
          <strong>It inherits every weakness of the covariance matrix.</strong>{" "}
          Σ appears in both the reverse optimization and the posterior update.
          Estimated correlations are unstable, and they tend to be wrong in
          precisely the direction that hurts during a crisis.
        </p>
      </Caveat>

      <InApp>
        <p>
          The engine uses a risk-aversion coefficient <code>δ = 2.5</code> and
          prior uncertainty <code>τ = 0.05</code> — both standard values from
          the literature. Views are entered per sector with an expected annual
          return and a confidence between 0 and 1, and are echoed back in the
          assumptions panel so you can see exactly what the model consumed. A
          view naming a sector outside the snapshot universe fails that column
          cleanly with <code>unknown_sector</code> and leaves the other two
          models untouched.
        </p>
        <p>
          Like the other engines it emits only <code>(μ, σ)</code> moments and
          lets the shared normalizer produce the comparable metrics. Next:{" "}
          <Link href="/learn/monte-carlo">
            Monte Carlo, which answers the range question
          </Link>
          .
        </p>
      </InApp>
    </LearnPage>
  );
}
