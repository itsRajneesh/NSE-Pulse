import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NSE Intraday Stock Screener & Signal Engine",
  description: "Automated Intraday Stock Screener & Quantitative Trade Signal Generator for Indian Stock Markets (NSE Nifty 50).",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="bg-dark-900 text-slate-100 min-h-screen antialiased selection:bg-indigo-500 selection:text-white">
        {children}
      </body>
    </html>
  );
}
