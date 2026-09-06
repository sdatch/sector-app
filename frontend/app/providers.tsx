"use client";

import { AuthProvider } from "@/lib/auth";
import Nav from "@/components/Nav";

export default function Providers({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <Nav />
      {children}
    </AuthProvider>
  );
}
