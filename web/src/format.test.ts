import { describe, expect, it } from "vitest";
import {
  formatAmount,
  formatDateTime,
  formatDistance,
  formatEuro,
  formatMinutes,
  formatQuantity,
  formatUnitPrice,
  haversineDistanceMeters,
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

describe("unit price formatting", () => {
  it("adds the base unit after the price", () => {
    expect(formatUnitPrice("1.15", "kg")).toBe("1,15 €/kg");
    expect(formatUnitPrice("0.95", "l")).toBe("0,95 €/l");
    expect(formatUnitPrice(2, "ud")).toBe("2,00 €/ud");
  });

  it("keeps the raw value when it cannot be parsed", () => {
    expect(formatUnitPrice("n/d", "kg")).toBe("n/d €/kg");
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

describe("distance formatting", () => {
  it("formats distances below 1000 meters in whole meters", () => {
    expect(formatDistance(450)).toBe("a 450 m");
    expect(formatDistance(450.4)).toBe("a 450 m");
    expect(formatDistance(0)).toBe("a 0 m");
    expect(formatDistance(999)).toBe("a 999 m");
  });

  it("formats distances of 1000 meters or more in kilometers with one Spanish decimal", () => {
    expect(formatDistance(1000)).toBe("a 1,0 km");
    expect(formatDistance(1200)).toBe("a 1,2 km");
    expect(formatDistance(1234)).toBe("a 1,2 km");
    expect(formatDistance(2500)).toBe("a 2,5 km");
  });

  it("computes haversine distance between coordinates", () => {
    // Plaza Mayor (León) to Mercadona Palomera (~220m)
    const p1 = { lat: 42.5987, lon: -5.5671 };
    const p2 = { lat: 42.6001, lon: -5.565 };
    const meters = haversineDistanceMeters(p1, p2);
    expect(meters).toBeGreaterThan(200);
    expect(meters).toBeLessThan(260);
    expect(formatDistance(meters)).toBe("a 232 m");
  });
});

