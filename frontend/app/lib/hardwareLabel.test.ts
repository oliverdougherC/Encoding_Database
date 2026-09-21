import { describe, expect, it } from "vitest";
import { realGpu } from "./hardwareLabel";

describe("realGpu", () => {
  it("treats placeholder GPU strings as absent so the CPU name surfaces", () => {
    for (const sentinel of ["not-applicable", "not_applicable", "Not Applicable", " N/A ", "none", "no-gpu", ""]) {
      expect(realGpu(sentinel)).toBeNull();
    }
    expect(realGpu(null)).toBeNull();
    expect(realGpu(undefined)).toBeNull();
  });

  it("passes real accelerator names through unchanged", () => {
    expect(realGpu("NVIDIA GeForce RTX 4070")).toBe("NVIDIA GeForce RTX 4070");
    expect(realGpu("Apple M2 Max")).toBe("Apple M2 Max");
  });
});
