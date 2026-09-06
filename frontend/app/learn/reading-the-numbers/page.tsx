import type { Metadata } from "next";
import Link from "next/link";
import LearnPage, { Caveat, Formula, InApp } from "@/components/LearnPage";

export const metadata: Metadata = {
  title: "Reading the numbers · Sector Insight",
  description:
    "What volatility, VaR, CVaR, Sharpe ratio, drawdown and Euler sector attribution mean — and where each one misleads.",
};

export default function Page() {
  return (
    <LearnPage slug="reading-the-numbers">
      <h2>Every column shows the same metrics</h2>
      <p>
        The three models produce their numbers in completely different ways, but
        they all report the same set of quantities, computed by one shared piece
        of code. That is deliberate: if each engine defined its own VaR
        convention, the columns would differ for reasons that had nothing to do
        with the models. Here is what each metric means.
      </p>

      <h2>Expected return</h2>
      <p>
        The average annual return the model implies, as a decimal. It is a{" "}
        <em>mean</em>, and means are pulled upward by the good tail — the typical
        outcome (the median, p50 in the distribution) is lower. A portfolio with
        an 8% expected return will not return 8% in most years. It will return
        something scattered widely around it.
      </p>

      <h2>Volatility</h2>
      <p>
        The annualized standard deviation of returns — how much the portfolio
        bounces around its average. A volatility of 0.16 means roughly two thirds
        of years land within ±16% of the average, and about one year in twenty
        falls more than 32% away from it.
      </p>
      <p>
        Volatility scales with the square root of time, not linearly. Four years
        of risk is twice one year&rsquo;s, not four times — which is the
        mathematical core of the case for long horizons.
      </p>
      <Formula note="the square-root-of-time rule used throughout the app">
        σ_horizon = σ_annual · √T
      </Formula>
      <p>
        Its main weakness is that it treats upside and downside identically. A
        portfolio that unexpectedly gained 30% registers as risky.
      </p>

      <h2>Value at Risk (VaR)</h2>
      <p>
        At 95% confidence, the loss your portfolio should not exceed in 95% of
        outcomes over the horizon. Shown as a positive number in currency: a VaR
        of $18,000 means &ldquo;in 19 of 20 scenarios you lose less than
        $18,000.&rdquo;
      </p>
      <p>
        The trap is what it omits. VaR is a threshold, and it says{" "}
        <strong>nothing whatsoever</strong> about the 1-in-20 case. Two portfolios
        with identical VaR can have wildly different disasters behind that line.
        VaR is also not additive — the VaR of a combined portfolio is not the sum
        of its parts — which is why it should never be summed across sectors.
      </p>

      <h2>Conditional VaR (CVaR / expected shortfall)</h2>
      <p>
        The average loss <em>given</em> that you are in the bad 5%. This is the
        number VaR is missing, and it is the one to look at if you care about
        genuinely bad outcomes. Regulators moved from VaR toward expected
        shortfall after 2008 for exactly this reason. CVaR is always larger than
        VaR; when it is <em>much</em> larger, the model is telling you the tail
        is nasty.
      </p>

      <h2>Sharpe ratio</h2>
      <Formula note="return per unit of risk">
        Sharpe = (μ − r_f) / σ
      </Formula>
      <p>
        How much return you earn above the risk-free rate per unit of volatility
        — the standard way to ask whether risk is being compensated. Roughly:
        below 0.5 is unimpressive, around 1.0 is good, and anything much above 2
        should make you suspicious of the inputs rather than impressed by the
        portfolio.
      </p>
      <p>
        Because the denominator is volatility, Sharpe penalizes upside surprises
        and is easily gamed by strategies that make steady money until they
        catastrophically do not.
      </p>

      <h2>Probability of loss</h2>
      <p>
        The chance of finishing below where you started. It falls sharply with
        horizon, because drift accumulates linearly while volatility only grows
        with √T. Watching this number change as you extend the horizon is the
        clearest demonstration in the app of what time actually does for an
        investor.
      </p>

      <h2>Maximum drawdown</h2>
      <p>
        The worst peak-to-trough decline along the path — reported by Monte Carlo
        only, since it requires simulating a path rather than an endpoint. This
        is the number that predicts whether you will abandon the plan. A
        portfolio you cannot hold through its drawdown has an expected return of
        zero, because you will not be there for the recovery.
      </p>

      <h2>Sector attribution — the part worth studying</h2>
      <p>
        The attribution chart splits your total return and total risk across
        sectors. The return split is easy: each sector contributes its weight
        times its expected return, and the parts add to the whole.
      </p>
      <p>
        The risk split is the interesting one, and it is not obvious. Risk is not
        additive — volatilities do not sum, because sectors partially offset each
        other. The app uses <strong>Euler decomposition</strong>, which
        apportions risk by asking how much total volatility would change if you
        added a little more of each sector:
      </p>
      <Formula note="these contributions sum exactly to portfolio volatility">
        RC_i = w_i · (Σw)_i / σ_p
      </Formula>
      <p>
        The payoff is the comparison between the two columns.{" "}
        <strong>When a sector&rsquo;s risk contribution exceeds its weight, it
        is punching above its size</strong> — usually because it is volatile,
        correlated with your other large holdings, or both. A sector at 20% of
        your money and 35% of your risk is where your portfolio actually lives.
      </p>
      <p>
        The reverse is also informative: a sector contributing less risk than its
        weight is doing diversification work for you. Occasionally a contribution
        is near zero or negative, meaning that holding is actively damping the
        portfolio&rsquo;s swings.
      </p>

      <h2>Estimation method</h2>
      <p>
        Every column declares how its numbers were derived, and this is not
        pedantry — a parametric VaR and a simulated VaR are different quantities
        even at the same confidence level.
      </p>
      <ul>
        <li>
          <code>parametric_factor</code> — Fama-French: closed-form from factor
          exposures.
        </li>
        <li>
          <code>parametric_normal</code> — Black-Litterman: closed-form from the
          posterior moments.
        </li>
        <li>
          <code>empirical_simulated</code> — Monte Carlo: read off the simulated
          distribution.
        </li>
      </ul>

      <Caveat>
        <p>
          <strong>Every one of these numbers is an estimate with error bars that
          are not shown.</strong> Precision in the display is not accuracy. A VaR
          of $18,432 is not meaningfully different from one of $19,000 — treat
          all of it as one significant figure and a direction.
        </p>
        <p>
          Metrics that depend on the tail (VaR, CVaR, p5) are the least reliable
          on screen, because they are estimated from the fewest observations and
          are the most sensitive to the normality assumption that real markets
          violate.
        </p>
      </Caveat>

      <InApp>
        <p>
          All six common metrics, the distribution percentiles, and the Euler
          attribution come from a single normalization module shared by all three
          engines. The engines supply raw moments or raw simulated paths and
          nothing else — they never implement horizon scaling, VaR signs, or
          attribution themselves. The property tests assert that the attribution
          sums exactly to portfolio volatility, and that the simulated metrics
          converge to the parametric ones as the path count grows.
        </p>
        <p>
          Now see{" "}
          <Link href="/learn/why-models-disagree">
            what is left once the conventions are shared
          </Link>
          .
        </p>
      </InApp>
    </LearnPage>
  );
}
