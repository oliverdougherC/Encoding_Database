const DEFAULT_CONTENT_CLASS = "mixed";
const DEFAULT_RESOLUTION = "1080p";
const DEFAULT_CRF = 24;
const DEFAULT_MIN_SAMPLES = 3;
const DEFAULT_PAGE = 1;

export const WORKBENCH_PAGE_SIZE = 50;

export type WorkbenchSortKey = "cpuModel" | "gpuModel" | "codec" | "crf" | "preset" | "";
export type EncoderTypeFilter = "" | "hardware" | "software";

export type WorkbenchSearchState = {
  page: number;
  cpu: string;
  gpu: string;
  codec: string;
  preset: string;
  sort: WorkbenchSortKey;
  dir: "asc" | "desc";
  encoderType: EncoderTypeFilter;
};

export type AnalyticsSearchState = {
  contentClass: string;
  resolution: string;
  crf: number;
  minSamples: number;
};

type ReadonlyURLSearchParamsLike = {
  get(name: string): string | null;
};

type SearchParamSource = URLSearchParams | ReadonlyURLSearchParamsLike;

function parsePositiveInt(raw: string | null | undefined, fallback: number): number {
  if (!raw || !/^\d+$/.test(raw.trim())) return fallback;
  const parsed = Number(raw);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) return fallback;
  return parsed;
}

export function parseWorkbenchSearchParams(params: SearchParamSource): WorkbenchSearchState {
  const sort = params.get("sort");
  const validSort = sort && ["cpuModel", "gpuModel", "codec", "crf", "preset"].includes(sort)
    ? (sort as WorkbenchSortKey)
    : "";
  const encoderType = params.get("encoderType");
  const validEncoderType = encoderType === "hardware" || encoderType === "software" ? encoderType : "";
  return {
    page: parsePositiveInt(params.get("page"), DEFAULT_PAGE),
    cpu: params.get("cpu") || "",
    gpu: params.get("gpu") || "",
    codec: params.get("codec") || "",
    preset: params.get("preset") || "",
    sort: validSort,
    dir: params.get("dir") === "asc" ? "asc" : "desc",
    encoderType: validEncoderType,
  };
}

export function buildWorkbenchSearchString(state: WorkbenchSearchState): string {
  const params = new URLSearchParams();
  if (state.page > 1) params.set("page", String(state.page));
  if (state.cpu) params.set("cpu", state.cpu);
  if (state.gpu) params.set("gpu", state.gpu);
  if (state.codec) params.set("codec", state.codec);
  if (state.preset) params.set("preset", state.preset);
  if (state.sort) params.set("sort", state.sort);
  if (state.dir !== "desc") params.set("dir", state.dir);
  if (state.encoderType) params.set("encoderType", state.encoderType);
  return params.toString();
}

export function parseAnalyticsSearchParams(params: SearchParamSource): AnalyticsSearchState {
  return {
    contentClass: params.get("contentClass") || DEFAULT_CONTENT_CLASS,
    resolution: params.get("resolution") || DEFAULT_RESOLUTION,
    crf: parsePositiveInt(params.get("crf"), DEFAULT_CRF),
    minSamples: parsePositiveInt(params.get("minSamples"), DEFAULT_MIN_SAMPLES),
  };
}

export function buildAnalyticsSearchString(state: AnalyticsSearchState): string {
  const params = new URLSearchParams();
  if (state.contentClass !== DEFAULT_CONTENT_CLASS) params.set("contentClass", state.contentClass);
  if (state.resolution !== DEFAULT_RESOLUTION) params.set("resolution", state.resolution);
  if (state.crf !== DEFAULT_CRF) params.set("crf", String(state.crf));
  if (state.minSamples !== DEFAULT_MIN_SAMPLES) params.set("minSamples", String(state.minSamples));
  return params.toString();
}
