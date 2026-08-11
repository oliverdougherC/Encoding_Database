import type { Benchmark } from "./lib/types";
import { fetchWorkbenchPage } from "./lib/api";
import { buildWorkbenchSearchString, parseWorkbenchSearchParams } from "./lib/queryState";
import BenchmarksTable from "./components/BenchmarksTable";
import HeroSearch from "./components/HeroSearch";
import styles from "./page.module.css";

export const revalidate = 60;
const toParams=(raw:Record<string,string|string[]|undefined>|undefined)=>{const p=new URLSearchParams();Object.entries(raw||{}).forEach(([k,v])=>{const value=Array.isArray(v)?v[0]:v;if(value)p.set(k,value)});return p};

export default async function Home({searchParams}:{searchParams?:Promise<Record<string,string|string[]|undefined>>}) {
  const state=parseWorkbenchSearchParams(toParams(searchParams?await searchParams:undefined)); let rows:Benchmark[]=[];let totalCount=0;let error:string|null=null;
  try { const data=await fetchWorkbenchPage(state);rows=data.rows;totalCount=data.totalCount; } catch(e) { error=e instanceof Error?e.message:"Unable to load benchmark results"; }
  const systems=new Set(rows.map(r=>`${r.cpuModel}|${r.gpuModel||""}`)).size, encoders=new Set(rows.map(r=>r.encoderName||r.codec)).size, codecs=new Set(rows.map(r=>r.codecFamily||r.codec)).size;
  return <div className={`page ${styles.page}`}>
    <section className={styles.hero}>
      <div className={styles.heroMain}><p className={styles.kicker}>Public benchmark database</p><h1>Brevity is the soul of wit.</h1><p className={styles.lede}>Community-submitted FFmpeg performance, quality, and efficiency data. Browse the corpus, inspect aggregate configurations, or filter to hardware you actually own.</p><HeroSearch className={styles.heroSearch}/>{!error&&<div className={styles.datasetLine}><span><strong>{totalCount.toLocaleString()}</strong> configurations</span><span><strong>{systems}</strong> systems on this page</span><span><strong>{encoders}</strong> encoders on this page</span></div>}</div>
      <aside className={styles.corpus}><p className={styles.kicker}>Corpus status</p><div className={styles.big}>{totalCount.toLocaleString()}</div><p className={styles.corpusLabel}>accepted aggregate configurations available to inspect</p><div className={styles.coverage}><div><strong>{systems}</strong><span>systems shown</span></div><div><strong>{encoders}</strong><span>encoders shown</span></div><div><strong>{codecs}</strong><span>codec families</span></div><div><strong>60s</strong><span>data refresh</span></div></div><p className={styles.callout}><strong>Transparent by design.</strong> Metrics are averages across accepted submissions with the same benchmark configuration.</p></aside>
    </section>
    <div className={styles.sectionHead} id="results"><div><h2>Browse results</h2><p>Aggregate benchmark configurations; open a row to inspect the retained fields.</p></div></div>
    {error ? <div className={styles.error}>Unable to load results: {error}</div> : <BenchmarksTable initialData={rows} totalCount={totalCount} currentPage={state.page}/>} 
    <aside className={styles.note}><strong>About these configurations</strong><span>Each row aggregates accepted submissions with the same benchmark configuration. Submission-specific software versions, timing, notes, and input provenance are not attributed to an aggregate.</span><a href={`/methodology?${buildWorkbenchSearchString(state)}`}>Read methodology</a></aside>
  </div>;
}
