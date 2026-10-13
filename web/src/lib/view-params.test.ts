import { describe, expect, it } from "vitest";
import { sanitizeParams } from "./view-params";

describe("sanitizeParams", () => {
  it("keeps only allowlisted, bounded keys", () => {
    expect(sanitizeParams("chain=bsc&minScore=50&evil=1&q=" + "x".repeat(65))).toEqual({ chain: "bsc", minScore: "50" });
    expect(sanitizeParams("")).toEqual({});
  });
});
