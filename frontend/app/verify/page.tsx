"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { devVerificationToken, requestVerify, verify } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function VerifyInner() {
  const { me, refresh } = useAuth();
  const params = useSearchParams();
  const router = useRouter();
  const [token, setToken] = useState(params.get("token") || "");
  const [status, setStatus] = useState<"idle" | "ok" | "error">("idle");
  const [busy, setBusy] = useState(false);
  const [devTried, setDevTried] = useState(false);

  async function doVerify(t: string) {
    setBusy(true);
    setStatus("idle");
    try {
      await verify(t);
      await refresh();
      setStatus("ok");
      setTimeout(() => router.push("/compare"), 800);
    } catch {
      setStatus("error");
    } finally {
      setBusy(false);
    }
  }

  // Local-dev convenience: pull the token from the dev endpoint and verify in
  // one step (404s in production, where a real email link is used instead).
  async function devAutoVerify() {
    try {
      const res = await devVerificationToken();
      if (res.token) {
        setToken(res.token);
        await doVerify(res.token);
      }
    } catch {
      /* endpoint disabled (prod) — fall back to manual paste */
    } finally {
      setDevTried(true);
    }
  }

  useEffect(() => {
    const t = params.get("token");
    if (t) {
      doVerify(t);
    } else if (me && !me.is_verified) {
      devAutoVerify(); // try the dev shortcut automatically
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me]);

  if (me?.is_verified) {
    return (
      <div className="container" style={{ maxWidth: 520 }}>
        <div className="card stack">
          <h1>You&apos;re verified ✓</h1>
          <p className="muted">Your email is confirmed. You can run comparisons.</p>
          <button className="btn primary" onClick={() => router.push("/compare")}>
            Start comparing
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="container" style={{ maxWidth: 560 }}>
      <div className="card stack">
        <h1>Verify your email</h1>
        <p className="muted">
          Verification is required before your first comparison.
        </p>

        <div className="notice">
          <strong>Local build:</strong> no mail server is wired up, so we can
          verify you directly here. Click the button below.
        </div>

        <button
          className="btn primary"
          disabled={busy}
          onClick={devAutoVerify}
        >
          {busy ? "Verifying…" : "Verify now (local dev)"}
        </button>

        {status === "ok" && (
          <div className="gain small">Verified! Redirecting…</div>
        )}
        {(status === "error" || devTried) && status !== "ok" && (
          <>
            <p className="muted small" style={{ marginTop: "0.5rem" }}>
              If that didn&apos;t work, paste the token from the backend logs
              (<code>docker compose logs backend | grep verify</code>) — copy the
              entire <code>token=…</code> value.
            </p>
            <div>
              <label>Verification token</label>
              <input
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
            </div>
            <div className="row">
              <button
                className="btn primary"
                disabled={busy || !token}
                onClick={() => doVerify(token)}
              >
                Verify with token
              </button>
              <button
                className="btn"
                disabled={busy || !me}
                onClick={() => me && requestVerify(me.email)}
              >
                Resend token
              </button>
            </div>
            {status === "error" && (
              <div className="error">That token is invalid or expired.</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default function VerifyPage() {
  return (
    <Suspense fallback={<div className="container">Loading…</div>}>
      <VerifyInner />
    </Suspense>
  );
}
