import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "newswatch",
  description: "Advisory news-to-action monitoring dashboard. Not financial advice.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
