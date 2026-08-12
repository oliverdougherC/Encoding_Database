export const WORKBENCH_PAGE_SIZE = 50;
export type WorkbenchSortKey = "cpuModel" | "gpuModel" | "codec" | "preset" | "fps" | "vmaf" | "fileSizeBytes" | "gpuPowerAvgW" | "samples" | "";
export type EncoderTypeFilter = "" | "hardware" | "software";
export type PlFitMode = "balanced" | "quality" | "storage" | "realtime" | "custom";
export type WorkbenchSearchState = { page:number; cpu:string; gpu:string; search:string; preset:string; sort:WorkbenchSortKey; dir:"asc"|"desc"; encoderType:EncoderTypeFilter };
export type AnalyticsSearchState = {
  workloadId?:string;
  environmentId?:string;
  environmentFingerprint?:string;
  contentClass:string;
  resolution:string;
  minSamples:number;
  fitMode: PlFitMode;
  customQualityWeight?: number | null;
  customBitrateWeight?: number | null;
  customSpeedWeight?: number | null;
  minimumQuality?: number | null;
  minimumRealtimeRatio?: number | null;
  maximumBitrateMbps?: number | null;
  compatibleCodecFamilies?: string | null;
  requireRecommendationEligibility?: boolean;
};
type Params = { get(name:string):string|null };
const sortKeys: WorkbenchSortKey[] = ["cpuModel","gpuModel","codec","preset","fps","vmaf","fileSizeBytes","gpuPowerAvgW","samples",""];
const positive = (value:string|null, fallback:number) => value && /^\d+$/.test(value) && Number(value)>0 ? Number(value) : fallback;
const numeric = (value:string|null) => value != null && value !== "" && Number.isFinite(Number(value)) ? Number(value) : null;
export function parseWorkbenchSearchParams(params:Params):WorkbenchSearchState { const sort=params.get("sort") as WorkbenchSortKey; const type=params.get("encoderType"); return { page:positive(params.get("page"),1), cpu:params.get("cpu")||"", gpu:params.get("gpu")||"", search:params.get("search")||"", preset:params.get("preset")||"", sort:sortKeys.includes(sort)?sort:"", dir:params.get("dir")==="asc"?"asc":"desc", encoderType:type==="hardware"||type==="software"?type:"" }; }
export function buildWorkbenchSearchString(state:WorkbenchSearchState):string { const p=new URLSearchParams(); if(state.page>1)p.set("page",String(state.page)); (["cpu","gpu","search","preset"] as const).forEach(k=>state[k]&&p.set(k,state[k])); if(state.sort)p.set("sort",state.sort); if(state.dir!=="desc")p.set("dir",state.dir); if(state.encoderType)p.set("encoderType",state.encoderType); return p.toString(); }
export function parseAnalyticsSearchParams(params:Params):AnalyticsSearchState {
  const fitModeParam = params.get("fitMode");
  const fitMode: PlFitMode = fitModeParam==="quality"||fitModeParam==="storage"||fitModeParam==="realtime"||fitModeParam==="custom" ? fitModeParam : "balanced";
  return {
    workloadId:params.get("workloadId")||"",
    environmentId:params.get("environmentId")||"",
    environmentFingerprint:params.get("environmentFingerprint")||"",
    contentClass:params.get("contentClass")||"mixed",
    resolution:params.get("resolution")||"1080p",
    minSamples:positive(params.get("minSamples"),3),
    fitMode,
    customQualityWeight:numeric(params.get("customQualityWeight")),
    customBitrateWeight:numeric(params.get("customBitrateWeight")),
    customSpeedWeight:numeric(params.get("customSpeedWeight")),
    minimumQuality:numeric(params.get("minimumQuality")),
    minimumRealtimeRatio:numeric(params.get("minimumRealtimeRatio")),
    maximumBitrateMbps:numeric(params.get("maximumBitrateMbps")),
    compatibleCodecFamilies:params.get("compatibleCodecFamilies"),
    requireRecommendationEligibility:params.get("requireRecommendationEligibility")==="1",
  };
}
export function buildAnalyticsSearchString(state:AnalyticsSearchState):string {
  const p=new URLSearchParams();
  if(state.workloadId)p.set("workloadId",state.workloadId);
  if(state.environmentId)p.set("environmentId",state.environmentId);
  if(state.environmentFingerprint)p.set("environmentFingerprint",state.environmentFingerprint);
  if(state.contentClass!=="mixed")p.set("contentClass",state.contentClass);
  if(state.resolution!=="1080p")p.set("resolution",state.resolution);
  if(state.minSamples!==3)p.set("minSamples",String(state.minSamples));
  if(state.fitMode!=="balanced")p.set("fitMode",state.fitMode);
  if(state.customQualityWeight!=null)p.set("customQualityWeight",String(state.customQualityWeight));
  if(state.customBitrateWeight!=null)p.set("customBitrateWeight",String(state.customBitrateWeight));
  if(state.customSpeedWeight!=null)p.set("customSpeedWeight",String(state.customSpeedWeight));
  if(state.minimumQuality!=null)p.set("minimumQuality",String(state.minimumQuality));
  if(state.minimumRealtimeRatio!=null)p.set("minimumRealtimeRatio",String(state.minimumRealtimeRatio));
  if(state.maximumBitrateMbps!=null)p.set("maximumBitrateMbps",String(state.maximumBitrateMbps));
  if(state.compatibleCodecFamilies)p.set("compatibleCodecFamilies",state.compatibleCodecFamilies);
  if(state.requireRecommendationEligibility)p.set("requireRecommendationEligibility","1");
  return p.toString();
}
