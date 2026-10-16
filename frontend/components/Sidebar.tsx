"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import DataHealthBadge from "./DataHealthBadge";
import ResetDemoButton from "./ResetDemoButton";
import { api } from "@/lib/api";

const NAV = [
  {
    href: "/",
    label: "Onboarding",
    hint: "Start here — load sample data",
    icon: (
      <path d="M3 10.5 12 3l9 7.5M5 9.5V21h14V9.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    ),
  },
  {
    href: "/estimate",
    label: "Estimate",
    hint: "RFP → P10/P50/P90",
    icon: (
      <path d="M4 19V5m0 14h16M8 15l3-4 3 2 4-6" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    ),
  },
  {
    href: "/history",
    label: "History",
    hint: "Projects & actuals",
    icon: (
      <path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    ),
  },
  {
    href: "/proof",
    label: "Proof",
    hint: "Replay & A/B evidence",
    icon: (
      <path d="M4 20V10m6 10V4m6 16v-7m4 7H2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    ),
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="no-print sticky top-0 z-40 flex h-screen w-14 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--bg-soft)]/80 backdrop-blur md:w-[224px]">
      <div className="flex items-center gap-2 px-3 py-4 md:px-4">
        <span className="flex h-8 w-8 items-center justify-center rounded-md border border-[rgba(34,211,238,0.5)] text-[var(--cyan)] shadow-[0_0_14px_rgba(34,211,238,0.25)]">
          <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden>
            <path d="M4 12h4l2-5 4 10 2-5h4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
        <div className="hidden md:block">
          <div className="num text-[13px] font-semibold tracking-[0.18em] text-[var(--text)]">
            THE ESTIMATOR
          </div>
          <div className="text-[10px] tracking-[0.22em] text-[var(--faint)]">
            RFP → RANGE
          </div>
        </div>
      </div>

      <nav className="mt-2 flex flex-1 flex-col gap-1 px-2" aria-label="Main">
        {NAV.map((item) => {
          const active =
            item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              title={item.hint}
              aria-current={active ? "page" : undefined}
              className={`group flex items-center gap-3 rounded-lg border px-2.5 py-2 text-sm transition ${
                active
                  ? "border-[rgba(34,211,238,0.4)] bg-[rgba(34,211,238,0.08)] text-[var(--text)]"
                  : "border-transparent text-[var(--dim)] hover:border-[var(--border)] hover:text-[var(--text)]"
              }`}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden className={active ? "text-[var(--cyan)]" : "text-[var(--faint)] group-hover:text-[var(--dim)]"}>
                {item.icon}
              </svg>
              <span className="hidden md:inline">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="hidden md:block">
        <div className="mx-3 mb-2">
          <ResetDemoButton />
        </div>
        <DataHealthBadge />
      </div>
      <div className="px-3 pb-3 pt-1 text-[10px] text-[var(--faint)]">
        <span className="hidden md:inline">API </span>
        <span className="num hidden truncate md:inline">{api.baseUrl}</span>
      </div>
    </aside>
  );
}
