import { fetchEncoderAnalytics } from "../lib/api";
import { parseAnalyticsSearchParams } from "../lib/queryState";
import type { EncoderAnalyticsRow } from "../lib/types";
import styles from "./page.module.css";

export const revalidate=60;
const params=(raw:Record<string,string|string[]|undefined>|undefined)=>{const p=new URLSearchParams();for(const[k,v]of Object.entries(raw||{})){const x=Array.isArray(v)?v[0]:v;if(x)p.set(k,x)}return p};

export default async function EncodersPage({searchParams}:{searchParams?:Promise<Record<string,string|string[]|undefined>>}) {
  let rows:EncoderAnalyticsRow[]=[];let error:string|null=null;
  try{rows=await fetchEncoderAnalytics(parseAnalyticsSearchParams(params(searchParams?await searchParams:undefined)))}catch(e){error=e instanceof Error?e.message:"Unable to load encoders"}
  const groups=new Map<string,EncoderAnalyticsRow[]>();rows.forEach(row=>groups.set(row.encoderName,[...(groups.get(row.encoderName)||[]),row]));
  const encoders=[...groups.entries()].sort((a,b)=>b[1].reduce((sum,row)=>sum+row.sampleCount,0)-a[1].reduce((sum,row)=>sum+row.sampleCount,0));
  return <div className={`page ${styles.page}`}><header><p className={styles.kicker}>Implementation index</p><h1>Encoders</h1><p>Encoder implementations and codec families represented in EncodingDB. Each card summarizes observed configuration coverage, speed, and quality.</p></header>{error?<p className={styles.error}>{error}</p>:<section className={styles.grid}>{encoders.map(([name,items])=>{const runs=items.reduce((sum,row)=>sum+row.sampleCount,0);const avgFps=items.reduce((sum,row)=>sum+row.avgFps,0)/items.length;const vmaf=items.filter(row=>row.avgVmaf!=null);const avgVmaf=vmaf.length?vmaf.reduce((sum,row)=>sum+(row.avgVmaf||0),0)/vmaf.length:null;return <article className={styles.card} key={name}><p className={styles.codec}>{items[0].codecFamily.toUpperCase()}</p><h2>{name}</h2><p className={styles.meta}>{items.length} configuration{items.length===1?"":"s"} · {runs} accepted run{runs===1?"":"s"}</p><dl><div><dt>Mean FPS</dt><dd>{avgFps.toFixed(1)}</dd></div><div><dt>Mean VMAF</dt><dd>{avgVmaf?.toFixed(2)||"—"}</dd></div></dl><div className={styles.presets}>{[...new Set(items.map(row=>row.preset))].slice(0,3).map(preset=><span key={preset}>{preset}</span>)}</div></article>})}{encoders.length===0&&<p className={styles.empty}>No verified encoder results are available for this benchmark slice yet.</p>}</section>}<aside className={styles.note}>Metrics are aggregate observations. Match workload and configuration before interpreting differences.</aside></div>
}
