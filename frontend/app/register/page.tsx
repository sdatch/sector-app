"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ApiError, login, register } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { DISCLAIMER_FULL } from "@/lib/types";

export default function RegisterPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();
  const { refresh } = useAuth();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!consent) {
      setError("You must consent to the disclaimer to create an account.");
      return;
    }
    setBusy(true);
    try {
      await register(email, password, consent);
      await login(email, password);
      await refresh();
      router.push("/verify");
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setError("Consent is required, or that email is already registered.");
      } else if (err instanceof ApiError && err.status === 422) {
        setError("Please provide a valid email and a stronger password.");
      } else {
        setError("Registration failed. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="container" style={{ maxWidth: 480 }}>
      <div className="card stack">
        <h1>Create your account</h1>
        <form onSubmit={submit} className="stack">
          <div>
            <label>Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div>
            <label>Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              required
            />
          </div>

          <div
            className="small muted"
            style={{
              maxHeight: 130,
              overflowY: "auto",
              border: "1px solid var(--border)",
              borderRadius: 8,
              padding: "0.6rem 0.8rem",
            }}
          >
            {DISCLAIMER_FULL}
          </div>

          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />
            <span className="small">
              I understand this is an educational tool and{" "}
              <strong>not financial advice</strong>, and I consent to the
              disclaimer above.
            </span>
          </label>

          {error && <div className="error">{error}</div>}
          <button className="btn primary" disabled={busy || !consent}>
            {busy ? "Creating…" : "Create account"}
          </button>
        </form>
        <p className="muted small">
          Already have an account? <Link href="/login">Log in</Link>
        </p>
      </div>
    </div>
  );
}
