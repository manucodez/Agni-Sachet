import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agni Sachet — Industrial Thermal Source Monitor",
  description: "Classification and monitoring of industrial fires and persistent thermal sources.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
