import { describe, expect, it } from "vitest";
import { address, InputError, number, sgtDateTime, slugify, url } from "./validate";

const fd = (o: Record<string, string>) => {
  const f = new FormData();
  Object.entries(o).forEach(([k, v]) => f.set(k, v));
  return f;
};

describe("validate", () => {
  it("converts SGT local times to UTC", () => {
    expect(sgtDateTime(fd({ t: "2026-10-13T08:00" }), "t")).toBe("2026-10-13T00:00:00.000Z");
    expect(() => sgtDateTime(fd({ t: "tomorrow" }), "t")).toThrow(InputError);
  });
  it("only accepts http(s) urls", () => {
    expect(url(fd({ u: "https://proj.example/x" }), "u")).toBe("https://proj.example/x");
    expect(() => url(fd({ u: "javascript:alert(1)" }), "u")).toThrow(InputError);
  });
  it("validates addresses per chain and normalises EVM case", () => {
    expect(address("base", "0xABCDEF0123456789abcdef0123456789ABCDEF01")).toBe("0xabcdef0123456789abcdef0123456789abcdef01");
    expect(() => address("solana", "0x" + "1".repeat(40))).toThrow(InputError);
    expect(() => address("bsc", "So11111111111111111111111111111111111111112")).toThrow(InputError);
  });
  it("numbers and slugs", () => {
    expect(number(fd({ n: "" }), "n")).toBeNull();
    expect(() => number(fd({ n: "-1" }), "n")).toThrow(InputError);
    expect(slugify("Proj Ü Token!! v2")).toBe("proj-u-token-v2");
  });
});
