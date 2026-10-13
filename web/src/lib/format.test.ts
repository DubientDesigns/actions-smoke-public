import { describe, expect, it } from "vitest";
import { formatAge, formatDuration, formatPct, formatPrice, formatSgt, formatUsd, freshness, toNum } from "./format";

describe("format", () => {
  it("never renders unknown as zero", () => {
    expect(formatUsd(null)).toBe("—");
    expect(formatPrice(undefined)).toBe("—");
    expect(formatPct("")).toBe("—");
    expect(toNum("abc")).toBeNull();
  });
  it("formats tiny prices with subscript zeros", () => {
    expect(formatPrice("0.000000012341")).toBe("$0.0₇1234");
    expect(formatPrice(0.00123)).toBe("$0.00123");
    expect(formatPrice(1234.5)).toBe("$1,234.5");
  });
  it("formats compact usd and pct", () => {
    expect(formatUsd(25000)).toBe("$25K");
    expect(formatUsd(512.345)).toBe("$512.35");
    expect(formatPct(3.21)).toBe("+3.2%");
    expect(formatPct(-1)).toBe("-1.0%");
  });
  it("displays in Singapore time", () => {
    expect(formatSgt("2026-10-13T00:00:00Z")).toContain("08:00");
    expect(formatSgt("2026-10-13T00:00:00Z")).toMatch(/SGT$/);
  });
  it("ages and freshness", () => {
    const now = new Date("2026-10-13T01:00:00Z");
    expect(formatAge("2026-10-13T00:58:30Z", now)).toBe("1m");
    expect(formatAge("2026-10-11T22:00:00Z", now)).toBe("1d 3h");
    expect(freshness("2026-10-13T00:50:00Z", 1800, now)).toBe("fresh");
    expect(freshness("2026-10-13T00:00:00Z", 1800, now)).toBe("aging");
    expect(freshness("2026-10-12T00:00:00Z", 1800, now)).toBe("stale");
    expect(freshness(null, 1800, now)).toBe("unknown");
  });
});

describe("formatDuration", () => {
  it("formats latency seconds", () => {
    expect(formatDuration(90)).toBe("1m");
    expect(formatDuration(null)).toBe("—");
  });
});
