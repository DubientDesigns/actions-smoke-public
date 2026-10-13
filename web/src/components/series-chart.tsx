"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatPrice, formatSgt, formatUsd } from "@/lib/format";

export type Point = { t: number; v: number };

/**
 * Single-series time chart. One measure per chart (price and liquidity are
 * shown as separate charts, never on a dual axis). Gaps in observation are
 * not interpolated over silently: points are plotted at their observed time.
 */
export function SeriesChart({ points, kind, label }: { points: Point[]; kind: "price" | "usd"; label: string }) {
  if (points.length < 2) {
    return <div className="flex h-48 items-center justify-center text-xs text-fg-dim">Not enough observations yet for {label.toLowerCase()}.</div>;
  }
  const fmt = kind === "price" ? formatPrice : (v: number) => formatUsd(v);
  return (
    <div className="h-48 w-full" role="img" aria-label={`${label} over time`}>
      <ResponsiveContainer>
        <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="0" vertical={false} />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(t) =>
              new Date(t).toLocaleString("en-SG", { timeZone: "Asia/Singapore", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false })
            }
            stroke="var(--fg-dim)"
            tick={{ fontSize: 10 }}
            tickLine={false}
            axisLine={{ stroke: "var(--border)" }}
            minTickGap={40}
          />
          <YAxis
            dataKey="v"
            width={72}
            domain={["auto", "auto"]}
            tickFormatter={(v) => fmt(v)}
            stroke="var(--fg-dim)"
            tick={{ fontSize: 10 }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            cursor={{ stroke: "var(--fg-dim)", strokeWidth: 1 }}
            contentStyle={{ background: "var(--panel-2)", border: "1px solid var(--border-strong)", borderRadius: 4, fontSize: 12 }}
            labelStyle={{ color: "var(--fg-muted)" }}
            itemStyle={{ color: "var(--fg)" }}
            labelFormatter={(t) => formatSgt(new Date(Number(t)))}
            formatter={(v) => [fmt(Number(v)), label]}
          />
          <Line type="linear" dataKey="v" stroke="var(--accent)" strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
