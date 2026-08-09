import type { Metadata } from "next";
import { Space_Grotesk, Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const display = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});
const body = Inter({ subsets: ["latin"], variable: "--font-body", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Incident Intelligence",
  description: "AI-native observability and incident intelligence platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body className="min-h-screen bg-void text-primary">
        <header className="border-b border-hairline px-6 py-4">
          <a href="/" className="font-display text-lg font-medium tracking-tight">
            INCIDENT<span className="text-ai">/</span>INTELLIGENCE
          </a>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
