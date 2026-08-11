import { fetchHardwareAnalytics } from "../lib/api";
import { parseAnalyticsSearchParams } from "../lib/queryState";
import type { HardwareAnalyticsRow } from "../lib/types";
import styles from "./page.module.css";

export const revalidate=60;
const params=(raw:Record<string,string|string[]|undefined>|undefined)=>{const p=new URLSearchParams();for(const[k,v]of Object.entries(raw||{})){const x=Array.isArray(v)?v[0]:v;if(x)p.set(k,x)}return p};

export default async function HardwarePage({searchParams}:{searchParams?:Promise<Record<string,string|string[]|undefined>>}) {
  let rows:HardwareAnalyticsRow[]=[];let error:string|null=null;
  try{rows=await fetchHardwareAnalytics(parseAnalyticsSearchParams(params(searchParams?await searchParams:undefined)))}catch(e){error=e instanceof Error?e.message:"Unable to load hardware"}
  const groups=new Map<string,HardwareAnalyticsRow[]>();
  rows.forEach(row=>{const name=row.gpuModel||row.cpuModel;groups.set(name,[...(groups.get(name)||[]),row])});
  const entities=[...groups.entries()].sort((a,b)=>b[1].reduce((sum,row)=>sum+row.sampleCount,0)-a[1].reduce((sum,row)=>sum+row.sampleCount,0));
  const runs=rows.reduce((sum,row)=>sum+row.sampleCount,0), encoders=new Set(rows.map(row=>row.encoderName)).size, codecs=new Set(rows.map(row=>row.codecFamily)).size;
  return <div className={`page ${styles.page}`}>
    <header className={styles.header}><div><p className={styles.kicker}>Entity index</p><h1>Hardware</h1><p>Browse hardware represented in the benchmark corpus. Entity summaries show observed encoder coverage and performance—without turning measurements into purchase recommendations.</p></div></header>
    <section className={styles.stats} aria-label="Hardware corpus summary"><Stat label="Hardware entities" value={entities.length} note="represented in this corpus slice"/><Stat label="Verified runs" value={runs} note="across aggregate configurations"/><Stat label="Encoder coverage" value={encoders} note={`${codecs} codec families represented`}/><Stat label="Data refresh" value="60s" note="cached analytics interval"/></section>
    <div className={styles.sectionHead}><div><h2>Hardware in corpus</h2><p>Sorted by number of accepted benchmark runs.</p></div></div>
    {error?<p className={styles.error}>{error}</p>:<section className={styles.list}>{entities.map(([name,items])=>{const samples=items.reduce((sum,row)=>sum+row.sampleCount,0);return <article key={name} className={styles.item}><span className={styles.entityIcon} aria-hidden="true">{name.replace(/[^A-Za-z0-9]/g,"").slice(0,2).toUpperCase()}</span><div className={styles.entityMain}><h2>{name}</h2><p>{items[0].gpuModel?items[0].cpuModel:"CPU / software encoding"} · {new Set(items.map(row=>row.codecFamily.toUpperCase())).size} codec families</p></div><dl><div><dt>Verified runs</dt><dd>{samples}</dd></div><div><dt>Encoders</dt><dd>{new Set(items.map(row=>row.encoderName)).size}</dd></div><div><dt>Mean FPS</dt><dd>{(items.reduce((sum,row)=>sum+row.avgFps,0)/items.length).toFixed(1)}</dd></div></dl></article>})}{entities.length===0&&<p className={styles.empty}>No verified hardware results are available for this benchmark slice yet.</p>}</section>}
    <aside className={styles.note}>Hardware pages report observed data; they do not make purchasing recommendations.</aside>
  </div>
}

function Stat({label,value,note}:{label:string;value:number|string;note:string}){return <div className={styles.stat}><span>{label}</span><strong>{typeof value==="number"?value.toLocaleString():value}</strong><small>{note}</small></div>}
