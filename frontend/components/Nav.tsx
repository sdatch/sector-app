"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

export default function Nav() {
  const { me, signOut } = useAuth();
  const router = useRouter();

  return (
    <nav className="nav">
      <Link href="/" className="brand">
        ◧ Sector Insight
      </Link>
      {me && (
        <>
          <Link href="/portfolios">Portfolios</Link>
          <Link href="/compare">Compare</Link>
          <Link href="/progress">Progress</Link>
          <Link href="/history">History</Link>
        </>
      )}
      {/* Educational content is public — it is the point of the product. */}
      <Link href="/learn">Learn</Link>
      <span className="spacer" />
      {me ? (
        <>
          <span className="muted small">{me.email}</span>
          {!me.is_verified && (
            <span className="badge provisional">unverified</span>
          )}
          <button
            className="btn"
            onClick={async () => {
              await signOut();
              router.push("/login");
            }}
          >
            Sign out
          </button>
        </>
      ) : (
        <>
          <Link href="/login">Log in</Link>
          <Link href="/register" className="btn primary">
            Register
          </Link>
        </>
      )}
    </nav>
  );
}
