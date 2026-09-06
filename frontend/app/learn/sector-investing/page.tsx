import type { Metadata } from "next";
import Link from "next/link";
import LearnPage, { Caveat, InApp } from "@/components/LearnPage";

export const metadata: Metadata = {
  title: "Sector investing · Sector Insight",
  description:
    "Why Sector Insight advises at the level of the sector rather than the trade, and what a sector tilt does to a portfolio.",
};

export default function Page() {
  return (
    <LearnPage slug="sector-investing">
      <h2>The unit of advice is the sector</h2>
      <p>
        Almost every investing tool answers <em>what should I buy or sell?</em>{" "}
        Sector Insight deliberately does not. It answers a different and, for a
        long-term investor, more useful question: <em>what am I exposed to, and
        what would change if I shifted that exposure?</em>
      </p>
      <p>
        A <strong>sector</strong> is a grouping of companies that make money in
        broadly the same way and therefore tend to suffer in the same weather.
        Utilities are rate-sensitive and defensive; Energy tracks the commodity
        cycle; Information Technology is long-duration growth. This app uses the
        eleven GICS sectors, the standard classification used across the
        industry:
      </p>
      <ul className="cols-2">
        <li>Information Technology</li>
        <li>Health Care</li>
        <li>Financials</li>
        <li>Consumer Discretionary</li>
        <li>Communication Services</li>
        <li>Industrials</li>
        <li>Consumer Staples</li>
        <li>Energy</li>
        <li>Utilities</li>
        <li>Real Estate</li>
        <li>Materials</li>
      </ul>

      <h2>Why sectors and not individual holdings</h2>
      <p>There are three reasons, and they compound.</p>
      <p>
        <strong>1. Most of your risk is not stock-specific.</strong> Once you
        hold more than a handful of names, the wobble unique to any one company
        largely cancels out against the others. What does not cancel is the part
        the holdings share — their common exposure to the economy, to rates, to
        the growth cycle. That shared part is what sector weights capture, and
        it is what actually determines whether your portfolio has a bad decade.
      </p>
      <p>
        <strong>2. Sector-level estimates are far more reliable.</strong>{" "}
        Estimating the expected return of a single stock is close to hopeless —
        the signal is tiny and the noise is enormous. Aggregating to eleven
        sectors averages away much of that noise, so the inputs the models
        depend on (means, volatilities, correlations) are estimated from
        something with enough statistical weight to be worth modeling. A model
        fed unreliable inputs produces confident-looking nonsense.
      </p>
      <p>
        <strong>3. Sector-level advice is actionable without being a
        recommendation.</strong> &ldquo;You are 46% Information Technology and
        the models disagree about whether that is compensated risk&rdquo; is
        something you can act on through whatever vehicles you already use.
        &ldquo;Sell NVDA&rdquo; is a securities recommendation, requires
        information this tool does not have about your taxes and your life, and
        is explicitly outside its scope.
      </p>

      <h2>Concentration is the thing to look for</h2>
      <p>
        The most common finding for a self-directed investor is unintended
        concentration. Someone who bought a handful of well-known winners over a
        decade often discovers they are two-thirds technology and communication
        services without ever having decided to be. It did not feel like a bet;
        it accumulated one purchase at a time.
      </p>
      <p>
        Concentration is not automatically wrong. It is a position, and the
        question is whether you are being paid for it. The comparison screen
        answers that from three directions at once: Fama-French tells you which
        systematic exposures the concentration creates, Black-Litterman tells you
        how far your mix sits from what the market as a whole holds, and Monte
        Carlo tells you what the bad tail looks like if the bet goes against you.
      </p>

      <h2>What a sector tilt actually does</h2>
      <p>
        A <strong>tilt</strong> is holding more or less of a sector than a
        neutral benchmark would. Tilting is not free and it is not symmetric:
      </p>
      <ul>
        <li>
          <strong>Expected return</strong> moves roughly linearly with the tilt —
          shift five points into a sector with a higher expected return and you
          add a small, proportional amount of expected return.
        </li>
        <li>
          <strong>Risk moves non-linearly</strong>, because it depends on
          correlation as well as weight. Adding to a sector that already
          correlates highly with your largest holding adds much more risk than
          the same weight added to something that behaves differently. This is
          why concentration hurts faster than it helps, and why the risk
          contribution column in the attribution chart is rarely proportional to
          the weight column.
        </li>
        <li>
          <strong>Diversification is the only genuinely free improvement</strong>{" "}
          available. Spreading across imperfectly correlated sectors lowers
          portfolio volatility without lowering expected return, because the
          portfolio&rsquo;s volatility is less than the weighted average of its
          parts whenever those parts are not perfectly correlated.
        </li>
      </ul>

      <h2>Three strategies the tool lets you reason about</h2>
      <p>
        <strong>Market-cap neutral.</strong> Hold each sector in proportion to
        its share of total market value. This is what a broad index fund does and
        it is the honest default — it requires no forecast at all. It is also
        the starting point Black-Litterman reverse-engineers its equilibrium
        returns from.
      </p>
      <p>
        <strong>Strategic tilt.</strong> Deviate permanently and deliberately
        from neutral because you believe a sector is structurally mispriced or
        because it hedges something specific about your life — an employee at an
        oil major may rationally underweight Energy, because their salary is
        already a large undiversified position in it.
      </p>
      <p>
        <strong>View-driven tilt.</strong> Express a specific forecast
        (&ldquo;Energy returns 8% next year&rdquo;) with a stated confidence, and
        let Black-Litterman work out how far to move given how uncertain you say
        you are. This is the disciplined version of acting on an opinion: a weak
        view moves the portfolio a little, a strong view moves it a lot, and you
        have to state which it is up front.
      </p>

      <Caveat>
        <p>
          Sector classification is a simplification with real edges. Amazon is
          Consumer Discretionary but a large part of its earnings is cloud
          computing. A megacap conglomerate spans several sectors internally.
          Sector membership is also not static — Real Estate was carved out of
          Financials in 2016, and Communication Services was substantially
          rebuilt in 2018.
        </p>
        <p>
          More importantly, sector weights are not the whole of your risk. They
          say nothing about your cash buffer, your time horizon, your tax
          situation, your job security, or your ability to sit through a 40%
          drawdown without selling. That last one has ended more investment plans
          than any modeling error.
        </p>
      </Caveat>

      <InApp>
        <p>
          Upload a CSV and the app derives sector weights from your{" "}
          <strong>quantities and current snapshot prices</strong>, not from
          stored weights — so your sector mix drifts with the market the way your
          real portfolio does. You can also skip the CSV entirely and enter
          target sector weights by hand, which turns the tool into a laboratory:
          set a mix, run the comparison, change one weight, run it again, and
          watch all three models respond.
        </p>
        <p>
          <strong>Funds are decomposed, not discarded.</strong> An index fund is
          not a sector — an S&amp;P 500 fund is roughly a third technology and
          spread across all eleven. So a fund holding is broken into the sectors
          it actually holds and each piece is added to the corresponding sector,
          which is the only way a portfolio of index funds can be given an honest
          sector mix. Two consequences worth knowing:
        </p>
        <ul>
          <li>
            The breakdowns are <strong>typical published allocations for a fund
            type</strong>, not live holdings — approximately right rather than
            exact.
          </li>
          <li>
            <strong>Only the equity sleeve is modeled.</strong> A bond fund has
            no equity sector exposure at all and is excluded; a 60/40 balanced
            fund contributes its 60, and the app tells you plainly what share of
            your money is sitting outside the model. Risk numbers for a
            bond-heavy account will look worse than the account behaves, because
            the damping half is invisible to a sector model.
          </li>
        </ul>
        <p>
          Next:{" "}
          <Link href="/learn/fama-french">
            how Fama-French decomposes that mix into factors
          </Link>
          .
        </p>
      </InApp>
    </LearnPage>
  );
}
