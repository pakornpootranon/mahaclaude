import { describe, expect, it } from "vitest";

import { formatDateBangkok, formatDateTimeBangkok, formatTimeBangkok, relativeFromNow } from "./time";

describe("formatDateTimeBangkok", () => {
  it("renders a UTC instant in Asia/Bangkok (UTC+7) with an ICT suffix", () => {
    // 2026-08-01T00:00:00Z -> 2026-08-01 07:00 in Bangkok
    expect(formatDateTimeBangkok("2026-08-01T00:00:00Z")).toBe("01 Aug 2026, 07:00 ICT");
  });

  it("rolls the date forward across the UTC/ICT day boundary", () => {
    // 2026-08-01T23:00:00Z -> 2026-08-02 06:00 in Bangkok
    expect(formatDateTimeBangkok("2026-08-01T23:00:00Z")).toBe("02 Aug 2026, 06:00 ICT");
  });

  it("returns an em dash for null/undefined/invalid input", () => {
    expect(formatDateTimeBangkok(null)).toBe("—");
    expect(formatDateTimeBangkok(undefined)).toBe("—");
    expect(formatDateTimeBangkok("not-a-date")).toBe("—");
  });
});

describe("formatDateBangkok", () => {
  it("renders just the date portion", () => {
    expect(formatDateBangkok("2026-08-01T00:00:00Z")).toBe("01 Aug 2026");
  });

  it("returns an em dash for missing input", () => {
    expect(formatDateBangkok(null)).toBe("—");
  });
});

describe("formatTimeBangkok", () => {
  it("renders just the time portion with an ICT suffix", () => {
    expect(formatTimeBangkok("2026-08-01T00:00:00Z")).toBe("07:00 ICT");
  });
});

describe("relativeFromNow", () => {
  it("returns an em dash for missing input", () => {
    expect(relativeFromNow(null)).toBe("—");
    expect(relativeFromNow(undefined)).toBe("—");
  });

  it("formats a recent timestamp as 'just now'", () => {
    expect(relativeFromNow(new Date())).toBe("just now");
  });

  it("formats a timestamp minutes ago", () => {
    const tenMinutesAgo = new Date(Date.now() - 10 * 60_000);
    expect(relativeFromNow(tenMinutesAgo)).toBe("10m ago");
  });

  it("formats a timestamp hours ago", () => {
    const threeHoursAgo = new Date(Date.now() - 3 * 3_600_000);
    expect(relativeFromNow(threeHoursAgo)).toBe("3h ago");
  });

  it("formats a timestamp days ago", () => {
    const twoDaysAgo = new Date(Date.now() - 2 * 86_400_000);
    expect(relativeFromNow(twoDaysAgo)).toBe("2d ago");
  });
});
