// src/app/layout.tsx
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Contract Auditor",
  description: "AI-powered adversarial audit for prediction market contracts",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-50 min-h-screen text-gray-900 antialiased">
        <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
          <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
            <a href="/" className="font-semibold text-gray-900 tracking-tight">
              Contract Auditor
            </a>
            <nav className="flex items-center gap-6 text-sm text-gray-600">
              <a href="/" className="hover:text-gray-900 transition-colors">
                New audit
              </a>
              <a
                href="/contracts"
                className="hover:text-gray-900 transition-colors"
              >
                History
              </a>
            </nav>
          </div>
        </header>
        <main className="max-w-5xl mx-auto px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
