import { describe, expect, it } from "vitest";
import {
  formatAmount,
  formatDateTime,
  formatEuro,
  formatMinutes,
  formatQuantity,
  parseDecimal,
} from "./format";

describe("parseDecimal", () => {
  it("accepts numbers and decimal strings with a dot or a comma", () => {
    expect(parseDecimal(2)).toBe(2);
    expect(parseDecimal("2.5")).toBe(2.5);
    expect(parseDecimal("2,5")).toBe(2.5);
  });

  it("returns NaN for values that are not numbers", () => {
    expect(Number.isNaN(parseDecimal("dos"))).toBe(true);
  });
});

describe("money formatting", () => {
  it("uses Spanish decimals and thousands separators", () => {
    expect(formatEuro("12.5")).toBe("12,50 €");
    expect(formatEuro(1234.5)).toBe("1234,50 €");
    expect(formatEuro(12345.5)).toBe("12.345,50 €");
    expect(formatAmount("1.5")).toBe("1,50");
  });

  it("keeps the raw value when it cannot be parsed", () => {
    expect(formatEuro("n/d")).toBe("n/d €");
  });
});

describe("quantity formatting", () => {
  it("drops trailing zeros", () => {
    expect(formatQuantity(2)).toBe("2");
    expect(formatQuantity("2.5")).toBe("2,5");
  });
});

describe("minutes formatting", () => {
  it("rounds decimal strings to whole minutes", () => {
    expect(formatMinutes("14.28")).toBe("14");
    expect(formatMinutes("14.62")).toBe("15");
    expect(formatMinutes(8)).toBe("8");
  });

  it("keeps the raw value when it cannot be parsed", () => {
    expect(formatMinutes("n/d")).toBe("n/d");
  });
});

describe("formatDateTime", () => {
  it("formats a timestamp as dd/mm/yyyy HH:mm", () => {
    expect(formatDateTime("2026-11-13T08:05:00")).toBe("13/11/2026 08:05");
  });

  it("returns the raw value when it is not a date", () => {
    expect(formatDateTime("ayer")).toBe("ayer");
  });
});
