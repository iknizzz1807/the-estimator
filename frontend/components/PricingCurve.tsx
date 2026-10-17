"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PricingBlock, PricingCurvePoint } from "@/lib/types";
import { fmtInt, fmtNum } from "@/lib/format";
import { Term } from "./Tooltip";

/** Standard normal CDF (Zelen & Severo; |error| < 7.5e-8), parity with the backend. */
function normalCdf(z: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(z));
  const density = 0.3989422804014327 * Math.exp((-z * z) / 2);
  const tail =
    density *
    t *
    (0.319381530 +
      t *
        (-0.356563782 +
          t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
  return z >= 0 ? 1 - tail : tail;
}

/**
 * P(actual > quote) under the same lognormal fit the backend uses for each
 * tier's `over_budget_prob` (packages.py::_over_budget_prob): continuous, so
 * the slider readout stays exact even between two curve points.
 */
function overrunProbability(pricing: PricingBlock, days: number): number {
  const { p10, p50, p90 } = pricing;
  if (!(days > 0 && p10 > 0 && p90 > p10 && p50 > 0)) {
    return days < p50 ? 1 : 0;
  }
  const sigma = (Math.log(p90) - Math.log(p10)) / (2 * 1.2816);
  const z = (Math.log(days) - Math.log(p50)) / sigma;
  return Math.min(0.999, Math.max(0.001, 1 - normalCdf(z)));
}

function riskTone(risk: number): { text: string; stroke: string; label: string; pill: string } {
  if (risk <= 0.25) {
    return {
      text: "text-[#27a644]",
      stroke: "#27a644",
      label: "comfortable",
      pill: "border-[rgba(39,166,68,0.3)] bg-[rgba(39,166,68,0.1)] text-[#27a644]",
    };
  }
  if (risk <= 0.5) {
    return {
      text: "text-[#f59e0b]",
      stroke: "#f59e0b",
      label: "risky",
      pill: "border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.1)] text-[#f59e0b]",
    };
  }
  return {
    text: "text-[#eb5757]",
    stroke: "#eb5757",
    label: "likely to overrun",
    pill: "border-[rgba(235,87,87,0.3)] bg-[rgba(235,87,87,0.1)] text-[#eb5757]",
  };
}

function CurveTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: PricingCurvePoint }>;
}) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div className="rounded-lg border border-[#23252a] bg-[#0f1011] p-2.5 text-xs shadow-2xl backdrop-blur-md">
      <div className="font-mono tabular-nums text-[#f7f8f8]">
        {fmtNum(point.days, 1)} days quoted
      </div>
      <div className="mt-1 font-mono text-[11px] tabular-nums text-[#828fff]">
        {fmtNum(point.over_prob * 100, 1)}% overrun risk
      </div>
    </div>
  );
}

/**
 * Interactive pricing curve (contract v0.2 `pricing` block, fitted from the
 * Full-scope interval): drag the quote slider over the curve to read the
 * overrun risk + implied margin, or jump to the smallest ≤25% / ≤10% quotes.
 * Adheres strictly to Linear design language: Surface-1 card (#0f1011),
 * hairline borders (#23252a), Linear lavender chart curve (#5e6ad2), and
 * high-precision tabular typography.
 */
export function PricingCurve({
  pricing,
  budgetDays,
}: {
  pricing: PricingBlock;
  /** The client budget the packages were built for (slider default). */
  budgetDays?: number | null;
}) {
  const curve = pricing.curve;
  const curveMin = curve.length > 0 ? curve[0].days : Math.max(1, pricing.p10 * 0.6);
  const curveMax =
    curve.length > 0 ? curve[curve.length - 1].days : Math.max(2, pricing.p90 * 1.5);

  const sliderMin = Math.max(1, Math.floor(curveMin));
  const sliderMax = Math.max(sliderMin + 1, Math.ceil(curveMax));
  const clampQuote = (value: number) =>
    Math.min(sliderMax, Math.max(sliderMin, Math.round(value)));

  // Default: the customer budget when it falls on the curve, else P50.
  const defaultQuote = useMemo(() => {
    const wanted = budgetDays && budgetDays > 0 ? budgetDays : pricing.p50;
    return clampQuote(wanted);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [budgetDays, pricing.p50, sliderMin, sliderMax]);

  const [quote, setQuote] = useState<number>(defaultQuote);

  // A rebuilt package set (new curve / budget) resets the slider default.
  useEffect(() => {
    setQuote(defaultQuote);
  }, [defaultQuote]);

  const risk = useMemo(() => overrunProbability(pricing, quote), [pricing, quote]);
  const tone = riskTone(risk);
  const marginPct = pricing.p50 > 0 ? ((quote - pricing.p50) / pricing.p50) * 100 : 0;

  if (curve.length === 0) return null;

  const minRisk = overrunProbability(pricing, sliderMin);
  const maxRisk = overrunProbability(pricing, sliderMax);

  return (
    <div
      className="space-y-4 rounded-lg border border-[#23252a] bg-[#0f1011] p-5 sm:p-6"
      id="pricing-curve"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#23252a]/70 pb-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[#8a8f98]">
            Pricing curve
          </div>
          <div className="text-xs text-[#62666d]">
            If I quote X days, what is the overrun risk?
          </div>
        </div>

        <span
          className="inline-flex items-center gap-1.5 rounded-full border border-[#23252a] bg-[#141516] px-2.5 py-0.5 font-mono text-[11px] tabular-nums text-[#8a8f98]"
          title={`Fitted from the ${pricing.scope}-scope interval`}
        >
          <span className="capitalize text-[#d0d6e0]">{pricing.scope} scope</span>
          <span>·</span>
          <span>P10–P90: {fmtInt(pricing.p10)}–{fmtInt(pricing.p90)}d</span>
        </span>
      </div>

      {/* Headline Readout */}
      <div
        className="flex flex-wrap items-baseline gap-x-3 gap-y-2"
        aria-live="polite"
        role="status"
      >
        <div className="font-mono text-xl font-semibold text-[#f7f8f8]">
          Quote {fmtInt(quote)} days
        </div>
        <span aria-hidden className="text-[#62666d]">
          →
        </span>
        <div className={`font-mono text-3xl font-bold tabular-nums ${tone.text}`}>
          {Math.round(risk * 100)}%
        </div>
        <span className="text-xs text-[#8a8f98]">
          overrun risk{" "}
          <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium tracking-wide ${tone.pill}`}>
            {tone.label}
          </span>
        </span>

        <span
          className={`inline-flex items-center rounded-full border px-2.5 py-0.5 font-mono text-[11px] tabular-nums ${
            marginPct >= 0
              ? "border-[rgba(94,106,210,0.3)] bg-[rgba(94,106,210,0.1)] text-[#828fff]"
              : "border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.1)] text-[#f59e0b]"
          }`}
          title="(quote − P50) ÷ P50 — the buffer priced into this quote"
        >
          margin {marginPct >= 0 ? "+" : ""}
          {fmtNum(marginPct, 1)}% vs P50
        </span>
      </div>

      {/* Linear Slider */}
      <div className="space-y-1.5 rounded-lg border border-[#23252a] bg-[#141516] p-3.5">
        <input
          type="range"
          min={sliderMin}
          max={sliderMax}
          step={1}
          value={quote}
          onChange={(event) => setQuote(Number(event.target.value))}
          className="w-full cursor-pointer accent-[#5e6ad2]"
          aria-label="Quote days"
          aria-valuetext={`${fmtInt(quote)} days, ${Math.round(risk * 100)}% overrun risk`}
        />
        <div className="flex justify-between font-mono text-[10.5px] tabular-nums text-[#62666d]">
          <span>
            Min: {fmtInt(sliderMin)}d ({Math.round(minRisk * 100)}% risk)
          </span>
          <span>
            Max: {fmtInt(sliderMax)}d ({Math.round(maxRisk * 100)}% risk)
          </span>
        </div>
      </div>

      {/* Safe Quote Quick Buttons */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-[11px] uppercase tracking-wider text-[#62666d]">
          Safe quotes:
        </span>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(39,166,68,0.3)] bg-[rgba(39,166,68,0.08)] px-2.5 py-1 font-mono text-xs tabular-nums text-[#27a644] transition-colors hover:border-[#27a644] hover:bg-[rgba(39,166,68,0.15)]"
          title="Smallest quote keeping overrun risk ≤ 25%"
          onClick={() => setQuote(clampQuote(pricing.safe_quote_25))}
        >
          <span>≤25% risk</span>
          <span>→</span>
          <strong className="font-semibold">{fmtInt(pricing.safe_quote_25)}d</strong>
        </button>

        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(94,106,210,0.3)] bg-[rgba(94,106,210,0.08)] px-2.5 py-1 font-mono text-xs tabular-nums text-[#828fff] transition-colors hover:border-[#5e6ad2] hover:bg-[rgba(94,106,210,0.15)]"
          title="Smallest quote keeping overrun risk ≤ 10%"
          onClick={() => setQuote(clampQuote(pricing.safe_quote_10))}
        >
          <span>≤10% risk</span>
          <span>→</span>
          <strong className="font-semibold">{fmtInt(pricing.safe_quote_10)}d</strong>
        </button>
      </div>

      {/* Recharts Area Curve */}
      <div className="h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={curve} margin={{ top: 8, right: 14, bottom: 0, left: -10 }}>
            <defs>
              <linearGradient id="linearPricingGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#5e6ad2" stopOpacity={0.25} />
                <stop offset="100%" stopColor="#5e6ad2" stopOpacity={0.01} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#23252a" strokeDasharray="3 6" vertical={false} />
            <XAxis
              dataKey="days"
              type="number"
              domain={["dataMin", "dataMax"]}
              tick={{ fill: "#62666d", fontSize: 10, fontFamily: "ui-monospace" }}
              stroke="#23252a"
              tickLine={false}
              tickFormatter={(value: number) => fmtInt(value)}
            />
            <YAxis
              domain={[0, 1]}
              tick={{ fill: "#62666d", fontSize: 10, fontFamily: "ui-monospace" }}
              stroke="#23252a"
              tickLine={false}
              tickFormatter={(value: number) => `${Math.round(value * 100)}%`}
              width={42}
            />
            <ChartTooltip content={<CurveTooltip />} />
            <ReferenceLine
              y={0.25}
              stroke="#27a644"
              strokeDasharray="2 6"
              strokeOpacity={0.7}
              label={{
                value: "25% safe line",
                position: "insideTopRight",
                fill: "#27a644",
                fontSize: 10,
                fontFamily: "sans-serif",
              }}
            />
            <ReferenceLine
              x={quote}
              stroke={tone.stroke}
              strokeDasharray="4 4"
              label={{
                value: `quote ${fmtInt(quote)}d · ${Math.round(risk * 100)}%`,
                position: "insideTopLeft",
                fill: tone.stroke,
                fontSize: 10,
                fontFamily: "ui-monospace",
              }}
            />
            <Area
              type="monotone"
              dataKey="over_prob"
              name="P(overrun)"
              stroke="#5e6ad2"
              strokeWidth={2}
              fill="url(#linearPricingGradient)"
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <p className="text-[11px] leading-relaxed text-[#62666d]">
        Risk model: a{" "}
        <Term
          term="Lognormal pricing"
          tip="Overrun risk is a lognormal fit through Full-scope P10/P50/P90 — the same shape the per-tier P(over budget) uses, so at the client's budget the numbers agree exactly."
        >
          <span className="text-[#8a8f98] underline decoration-dotted decoration-[#62666d] underline-offset-2">
            lognormal distribution fit
          </span>
        </Term>{" "}
        through the Full-scope P10/P50/P90. At the client&apos;s budget the tier number and this curve agree.
      </p>
    </div>
  );
}
