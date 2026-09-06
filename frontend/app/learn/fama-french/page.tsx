import type { Metadata } from "next";
import Link from "next/link";
import LearnPage, { Caveat, Formula, InApp } from "@/components/LearnPage";

export const metadata: Metadata = {
  title: "Fama-French 5-factor · Sector Insight",
  description:
    "How the Fama-French five-factor model decomposes portfolio risk into market, size, value, profitability and investment factors.",
};

export default function Page() {
  return (
    <LearnPage slug="fama-french">
      <h2>The question it answers</h2>
      <p>
        <strong>What is actually driving my risk and return?</strong> Fama-French
        does not try to tell you what to hold. It takes the portfolio you already
        have and explains it — breaking its behaviour down into a handful of
        broad, systematic forces that move all assets at once.
      </p>

      <h2>The idea</h2>
      <p>
        In 1964 the Capital Asset Pricing Model proposed that only one thing
        matters: how much a holding moves with the overall market. Decades of
        data said otherwise. Small companies beat large ones by more than their
        market exposure explained. Cheap companies beat expensive ones. Eugene
        Fama and Kenneth French — Fama shared the 2013 Nobel for this line of
        work — showed that adding factors for those effects explained far more of
        what portfolios actually do, and in 2015 extended the set to five.
      </p>
      <p>
        The mechanism is a <strong>regression</strong>: take a long history of
        returns, and ask statistically how much of each sector&rsquo;s movement
        is explained by each factor. The answers are called{" "}
        <strong>loadings</strong> (or betas). A loading of 1.2 on the market
        factor means that sector historically moved about 20% more than the
        market did. A loading near zero means that factor is essentially
        irrelevant to it.
      </p>

      <h2>The five factors</h2>
      <table>
        <thead>
          <tr>
            <th>Factor</th>
            <th>Name</th>
            <th>What it captures</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <code>MKT</code>
            </td>
            <td>Market</td>
            <td>
              The return of the whole market above the risk-free rate. Nearly
              everything loads positively; this is usually the dominant term.
            </td>
          </tr>
          <tr>
            <td>
              <code>SMB</code>
            </td>
            <td>Size (Small Minus Big)</td>
            <td>
              Small companies minus large ones. Positive loading means the
              portfolio behaves like smaller companies.
            </td>
          </tr>
          <tr>
            <td>
              <code>HML</code>
            </td>
            <td>Value (High Minus Low)</td>
            <td>
              Cheap companies (high book-to-market) minus expensive ones.
              Positive means value-like; negative means growth-like.
            </td>
          </tr>
          <tr>
            <td>
              <code>RMW</code>
            </td>
            <td>Profitability (Robust Minus Weak)</td>
            <td>
              Consistently profitable companies minus marginal ones. Positive
              means a tilt toward quality earnings.
            </td>
          </tr>
          <tr>
            <td>
              <code>CMA</code>
            </td>
            <td>Investment (Conservative Minus Aggressive)</td>
            <td>
              Companies that grow their asset base slowly minus those that
              expand aggressively. Positive means a disciplined-capital tilt.
            </td>
          </tr>
        </tbody>
      </table>

      <h2>How the numbers are produced</h2>
      <p>
        Once each sector&rsquo;s loadings are estimated, expected return is the
        risk-free rate plus each loading multiplied by that factor&rsquo;s
        long-run premium — the historical reward for bearing it:
      </p>
      <Formula note="expected return for each sector">
        μ = r_f + (loadings × factor premia)
      </Formula>
      <p>
        Risk is built the same way. A sector&rsquo;s variance comes from its
        factor exposures plus whatever the factors could not explain
        (residual, or idiosyncratic, risk):
      </p>
      <Formula note="covariance across sectors">
        Σ = B · Σ_factors · Bᵀ + diag(residual variance)
      </Formula>
      <p>
        Your portfolio&rsquo;s expected return and volatility then follow from
        your sector weights <code>w</code>:
      </p>
      <Formula>μ_p = w · μ &nbsp;&nbsp;&nbsp; σ_p = √(wᵀ Σ w)</Formula>
      <p>
        This is fast — pure linear algebra over small matrices, a millisecond of
        work — which is why the Fama-French column is complete on the first
        paint of the comparison screen while Monte Carlo is still running.
      </p>

      <h2>What to look at in the output</h2>
      <ul>
        <li>
          <strong>Factor loadings.</strong> The most informative thing the model
          gives you. A portfolio that feels diversified across ten sectors but
          shows a large negative <code>HML</code> loading is making one
          concentrated bet — on growth over value — through ten different doors.
        </li>
        <li>
          <strong>R²</strong> (shown in the assumptions panel). The share of
          movement the five factors explain. High R² means the model has a real
          grip on this portfolio; low R² means much of your risk is specific and
          the factor story is incomplete.
        </li>
        <li>
          <strong>Residual volatility.</strong> The part the factors do not
          explain. Historically this has not been reliably rewarded — you bear
          it without expecting to be paid for it.
        </li>
      </ul>

      <Caveat>
        <p>
          <strong>It is backward-looking by construction.</strong> Loadings and
          premia are estimated from history. If a sector&rsquo;s character has
          changed — technology shifting from cyclical hardware to recurring
          software revenue — the regression is describing a portfolio that no
          longer exists.
        </p>
        <p>
          <strong>Factor premia are far less certain than they look.</strong> The
          equity premium is estimated with wide error bars even after a century
          of data, and the size premium in particular has been weak-to-absent for
          long stretches since it was published. A single premium number hides a
          genuinely large confidence interval.
        </p>
        <p>
          <strong>It assumes a stable, linear, normal world.</strong> Loadings
          are treated as constant, relationships as linear, and returns as
          well-behaved. In a crisis, correlations converge toward one and
          precisely the diversification the model credits you with stops working.
        </p>
      </Caveat>

      <InApp>
        <p>
          The engine regresses each sector&rsquo;s excess returns on all five
          factors with an intercept, annualizes the resulting premia and
          covariances by 252 trading days, and applies 10% linear shrinkage
          toward the diagonal of the covariance matrix to keep it
          well-conditioned. It reports <code>parametric_factor</code> as its
          estimation method, and its R² per sector appears in the assumptions
          panel.
        </p>
        <p>
          Critically, it does <em>not</em> compute its own VaR or attribution.
          It hands its <code>(μ, σ)</code> to the shared normalizer that all
          three models use — which is exactly why the three columns are
          comparable.{" "}
          <Link href="/learn/why-models-disagree">
            More on that here
          </Link>
          .
        </p>
      </InApp>
    </LearnPage>
  );
}
