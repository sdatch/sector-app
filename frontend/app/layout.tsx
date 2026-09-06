import type { Metadata } from "next";
import "./globals.css";
import Providers from "./providers";
import { DisclaimerFooter } from "@/components/Disclaimer";

export const metadata: Metadata = {
  title: "Sector Insight",
  description:
    "Three risk models, one portfolio — see where your risk concentrates and why models disagree.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <main>{children}</main>
        </Providers>
        <DisclaimerFooter />
      </body>
    </html>
  );
}
