import type { Benchmark } from "./lib/types";
import { fetchWorkbenchPage } from "./lib/api";
import { buildWorkbenchSearchString, parseWorkbenchSearchParams } from "./lib/queryState";
import BenchmarksTable from "./components/BenchmarksTable";
import styles from "./page.module.css";

export const revalidate = 60;
const toParams=(raw:Record<string,string|string[]|undefined>|undefined)=>{const p=new URLSearchParams();Object.entries(raw||{}).forEach(([k,v])=>{const value=Array.isArray(v)?v[0]:v;if(value)p.set(k,value)});return p};

export default async function Home({searchParams}:{searchParams?:Promise<Record<string,string|string[]|undefined>>}) {
  const state=parseWorkbenchSearchParams(toParams(searchParams?await searchParams:undefined)); let rows:Benchmark[]=[];let totalCount=0;let error:string|null=null;
  try { const data=await fetchWorkbenchPage(state);rows=data.rows;totalCount=data.totalCount; } catch(e) { error=e instanceof Error?e.message:"Unable to load benchmark results"; }
  const systems=new Set(rows.map(r=>`${r.cpuModel}|${r.gpuModel||""}`)).size, encoders=new Set(rows.map(r=>r.encoderName||r.codec)).size;
  return <div className={`page ${styles.page}`}>
    <header className={styles.intro}><p className={styles.kicker}>Public encoding benchmark database</p><h1>Brevity is the soul of wit.</h1><p>Community-submitted FFmpeg performance, quality, and efficiency data.</p></header>
    {!error && <p className={styles.summary}><strong>{totalCount.toLocaleString()}</strong> verified runs <span>·</span> {systems.toLocaleString()} systems represented <span>·</span> {encoders.toLocaleString()} encoder implementations <span>·</span> updated from the public corpus</p>}
    {error ? <div className={styles.error}>Unable to load results: {error}</div> : <BenchmarksTable initialData={rows} totalCount={totalCount} currentPage={state.page}/>} 
    <aside className={styles.note}><strong>About these results</strong><span>Rows are public observations, not recommendations. Inspect run details and methodology before drawing conclusions.</span><a href={`/methodology?${buildWorkbenchSearchString(state)}`}>Read methodology</a></aside>
  </div>;
}
