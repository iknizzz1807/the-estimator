import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/Sidebar";
import OfflineNotice from "@/components/OfflineNotice";

export const metadata: Metadata = {
  title: "The Estimator — from RFP to range",
  description:
    "Paste a client email, get a calibrated P10/P50/P90 effort estimate, ranked clarifying questions and a system that learns from every finished project. Workflow dashboard — no chat.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <div className="flex min-h-screen">
          <Sidebar />
          <div className="flex min-w-0 flex-1 flex-col">
            <OfflineNotice />
            <main className="mx-auto w-full max-w-[1440px] flex-1 px-5 py-6 lg:px-8">
              {children}
            </main>
            <footer className="no-print px-5 pb-6 text-[11px] text-[var(--faint)] lg:px-8">
              Hackathon demo build · synthetic data · estimates are ranges, not
              promises.
            </footer>
          </div>
        </div>
      </body>
    </html>
  );
}
