#!/usr/bin/env node
// Operator-only, create-only review packet. Never invents reviewer decisions or activates scoring.
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { validateReviewMediaMap, validateReviewMediaPath } from './calibration-review-media.mjs';
import { fileURLToPath } from 'node:url';
const flags = new Map();
for (let i=2;i<process.argv.length;i+=2) flags.set(process.argv[i],process.argv[i+1]);
if (!flags.get('--evidence') || !flags.get('--output')) throw new Error('Usage: build-calibration-review-packet.mjs --evidence DRAFT.json --output NEW_DIRECTORY [--media-map MAP.json] [--reference-map REFERENCES.json]');
const server = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../server');
const { parseCalibrationEvidence, assessCalibrationEvidence, CALIBRATION_SCENARIOS, HOLDOUT_DIMENSIONS, METRIC_SANITY_CASES } = await import(path.join(server,'dist/v7/calibration.js'));
const evidence = parseCalibrationEvidence(await readFile(flags.get('--evidence'),'utf8'));
const assessment = assessCalibrationEvidence(evidence);
const media = validateReviewMediaMap(flags.get('--media-map') ? JSON.parse(await readFile(flags.get('--media-map'),'utf8')) : {});
const references = flags.get('--reference-map') ? JSON.parse(await readFile(flags.get('--reference-map'), 'utf8')) : {};
for (const entry of Object.values(references)) {
  validateReviewMediaPath(entry.playbackPath);
  validateReviewMediaPath(entry.originalPath);
  if (entry.pixelVerified !== true || !/^[a-f0-9]{64}$/.test(entry.sourceSha256) || !/^[a-f0-9]{64}$/.test(entry.previewSha256) || !Number.isInteger(entry.decodedFrames) || entry.decodedFrames < 1) throw new Error('Reference requires a hash-bound pixel verification receipt');
}
for (const row of evidence.corpus) {
  if (references[row.workloadId] && references[row.workloadId].sourceSha256 !== row.sourceSha256) throw new Error('Reference receipt does not match the exact evidence source');
}
const groups = new Map();
for(const row of evidence.corpus) {
  const key = JSON.stringify([row.workloadId,row.environmentFingerprint]);
  const entries = groups.get(key) ?? []; entries.push(row); groups.set(key,entries);
}
const comparisons = [...groups.values()].map(rows => {
  // One observation per exact recipe, deterministically chosen; repetitions remain in the full corpus.
  const recipes = new Map();
  for(const row of [...rows].sort((a,b)=>a.evidenceId.localeCompare(b.evidenceId))) if(!recipes.has(row.recipeFingerprint)) recipes.set(row.recipeFingerprint,row);
  return [...recipes.values()].sort((a,b)=>a.recipeFingerprint.localeCompare(b.recipeFingerprint));
}).filter(rows=>rows.length>=2).sort((a,b)=>a[0].workloadId.localeCompare(b[0].workloadId)||a[0].environmentFingerprint.localeCompare(b[0].environmentFingerprint));
const families = [...new Set(evidence.corpus.flatMap(row => [`encoder:${row.encoderImplementation}`, ...(row.hardwareFamily === 'software' ? [] : [`hardware:${row.hardwareFamily}`])]))].sort();
const requiredReviews = [
  ...CALIBRATION_SCENARIOS.map(scenario => ({ kind: 'Golden choice', scope: scenario })),
  ...HOLDOUT_DIMENSIONS.map(dimension => ({ kind: 'Held-out validation', scope: dimension, note: dimension === 'CONTENT_CLASS' ? 'All seven predeclared content-class folds must be evaluated.' : undefined })),
  ...families.map(family => ({ kind: 'Top-family choice', scope: family })),
  ...METRIC_SANITY_CASES.map(caseType => ({ kind: 'Metric sanity', scope: caseType })),
].map(task => ({ ...task, status: 'NOT_READY_FOR_SIGNOFF', reviewer: null, decision: null,
  reason: 'Exact final comparison membership, objective coverage and independently fitted ranking evidence must be completed before this calibration sign-off. The observed-media catalog is available for inspection.' }));
const manifest = { schemaVersion:'encodingdb-calibration-review-packet/v1', evidenceHash:evidence.evidenceHash,
  status:'DRAFT_REQUIRES_MEASUREMENT_COVERAGE_AND_GENUINE_REVIEW', assessment,
  comparisons:comparisons.map((rows,index)=>({comparisonId:`comparison-${index+1}`,workloadId:rows[0].workloadId,contentClass:rows[0].contentClass,environmentFingerprint:rows[0].environmentFingerprint,candidateEvidenceIds:rows.map(row=>row.evidenceId)})),
  rows:evidence.corpus.map(row=>({...row,media:media[row.artifactSha256]??null})),
  requiredReviews, references, decisions:[], reviewer:null,
  instructions:'Record independent perceptual observations before inspecting PL predictions. These comparisons are evidence preparation, not executed holdout validation. Repetitions are not independent machines. Missing media, coverage, folds or human judgments block freeze.' };
const output=path.resolve(flags.get('--output'));await mkdir(output,{recursive:false});
await writeFile(path.join(output,'manifest.json'),JSON.stringify(manifest,null,2)+'\n',{flag:'wx'});
await writeFile(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2)+'\n',{flag:'wx'});
// Escape '<' so source metadata cannot terminate the JSON data element.
const payload=JSON.stringify(manifest).replaceAll('<','\\u003c');
const html=`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PL evidence review</title><link rel="icon" href="data:,"><style>
[hidden]{display:none!important}:root{font-family:system-ui,sans-serif;color:#17232c;background:#f3f5f6}body{max-width:1200px;margin:32px auto;padding:0 22px}h1{font-size:30px;margin-bottom:8px}p{line-height:1.5}.status{border-left:3px solid #af742c;padding:10px 15px;background:#fff}label{display:block;margin-top:16px;font-weight:600}input,select,textarea,button{font:inherit;border:1px solid #bfcbd3;border-radius:6px;padding:9px;background:white}select,textarea{width:100%;box-sizing:border-box}textarea{min-height:90px}button{cursor:pointer;background:#173d51;color:white;margin-top:16px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:18px;margin-top:20px}article{background:white;border:1px solid #dce1e5;padding:15px;border-radius:9px;min-width:0}video{width:100%;max-height:290px;background:#111}code{overflow-wrap:anywhere;font-size:11px}dt{font-weight:600}dd{margin:0 0 8px}details{margin-top:24px}small{display:block;line-height:1.5;color:#4a5e6b}.row{display:flex;gap:12px;flex-wrap:wrap}.row label{flex:1}.row input{width:100%;box-sizing:border-box}</style>
<h1>PL evidence review</h1><p>Compare retained encodes and record your observations. No score is approved by this packet.</p><p class="status" id="status"></p><h2>Required decisions</h2><p id="review-readiness"></p><details><summary>Show exact review requirements</summary><ul id="required-reviews"></ul></details><h2>Observed-media catalog</h2><p>Inspection only. These comparisons are not requests to approve an incomplete experiment.</p><div class="row" hidden><label>Your name or reviewer ID<input id="reviewer" autocomplete="name"></label><label>Relevant expertise<input id="expertise"></label></div><label for="comparison">Comparable candidates</label><select id="comparison"></select><div id="reference"></div><div id="cards" class="grid"></div><div hidden><label for="scenario">Decision scenario</label><select id="scenario"><option>BALANCED</option><option>QUALITY</option><option>STORAGE</option><option>REALTIME</option><option>METRIC_SANITY</option></select><label for="choice">Preferred candidate</label><select id="choice"></select><label for="rationale">Why, and what visible artifacts or tradeoffs affected your choice?</label><textarea id="rationale"></textarea><button id="save">Save this observation</button> <button id="download">Download review responses</button><p id="feedback" aria-live="polite"></p></div><details><summary>Remaining validation requirements</summary><ul id="findings"></ul></details><small>Original evidence remains immutable. Downloaded responses require reconciliation with exact retained evidence, completed folds and production ranking before any calibration freeze.</small>
<script type="application/json" id="data">${payload}</script><script>
const p=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id),responses=[];
$('review-readiness').textContent='0 of '+p.requiredReviews.length+' review categories are ready for final sign-off. Complete objective validation first; no human decision has been preselected.';for(const task of p.requiredReviews){const li=document.createElement('li');li.textContent=task.kind+' · '+task.scope+' — '+task.status+(task.note?' · '+task.note:'');$('required-reviews').append(li);}
$('status').textContent=p.rows.length+' retained observations; '+p.comparisons.length+' comparable groups; '+p.assessment.errors.length+' validation findings. Status: review preparation only.';
function option(value,text){const o=document.createElement('option');o.value=value;o.textContent=text;return o;}
for(const c of p.comparisons)$('comparison').append(option(c.comparisonId,c.workloadId+' · '+c.candidateEvidenceIds.length+' recipes · '+c.environmentFingerprint.slice(0,10)));
for(const f of p.assessment.errors){const li=document.createElement('li');li.textContent=f.code+': '+f.message;$('findings').append(li);}
function render(){const c=p.comparisons.find(c=>c.comparisonId===$('comparison').value);$('cards').replaceChildren();$('choice').replaceChildren(option('','No decision / further evidence needed'));$('reference').replaceChildren();if(!c)return;const ref=p.references[c.workloadId];if(ref){const box=document.createElement('details'),title=document.createElement('summary'),v=document.createElement('video'),a=document.createElement('a');title.textContent='View source reference · pixel-identical lossless preview';v.controls=true;v.preload='metadata';v.src=ref.playbackPath;v.style.maxWidth='640px';a.href=ref.originalPath;a.textContent='Download unchanged original reference';box.append(title,v,a);$('reference').append(box);}c.candidateEvidenceIds.forEach((id,index)=>{const r=p.rows.find(r=>r.evidenceId===id),a=document.createElement('article'),h=document.createElement('h2');h.textContent='Candidate '+(index+1);a.append(h);if(r.media?.playbackPath){const v=document.createElement('video');v.controls=true;v.preload='metadata';v.src=r.media.playbackPath;v.addEventListener('error',()=>{const e=document.createElement('p');e.textContent='This browser cannot play this artifact. Open its original media with a compatible native player.';a.append(e);});a.append(v);const link=document.createElement('a');link.href=r.media.originalPath??r.media.playbackPath;link.textContent='Open original retained media';a.append(link);}else{const note=document.createElement('p');note.textContent='Media not included. Do not record a perceptual decision without viewing the exact artifact.';a.append(note);}const dl=document.createElement('dl');for(const [k,v]of Object.entries({Recipe:r.encoderImplementation+' / '+r.preset,Control:JSON.stringify(r.nativeRateControl),Bitrate:(r.videoBitrateBps/1e6).toFixed(2)+' Mb/s',Speed:r.realTimeRatio.toFixed(2)+'× realtime',Quality:r.vmafMean.toFixed(2)+' mean / '+r.vmafP5.toFixed(2)+' p5 VMAF',Status:r.runStatus})){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k;dd.textContent=v;dl.append(dt,dd);}a.append(dl);const code=document.createElement('code');code.textContent=r.artifactSha256;a.append(code);$('cards').append(a);$('choice').append(option(id,'Candidate '+(index+1)));});$('rationale').value='';}
$('comparison').onchange=render;render();
$('save').onclick=()=>{if(!$('reviewer').value.trim()||$('expertise').value.trim().length<12||$('rationale').value.trim().length<20){$('feedback').textContent='Please supply reviewer identity, relevant expertise and a substantive rationale.';return;}responses.push({comparisonId:$('comparison').value,scenario:$('scenario').value,selectedEvidenceId:$('choice').value||null,rationale:$('rationale').value.trim(),reviewer:{reviewerId:$('reviewer').value.trim(),expertise:$('expertise').value.trim(),reviewedAt:new Date().toISOString()}});$('feedback').textContent=responses.length+' observations saved in this page. Download before closing.';};
$('download').onclick=()=>{const data={schemaVersion:'encodingdb-calibration-review-responses/v1',evidenceHash:p.evidenceHash,decisions:responses};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='calibration-review-responses.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
</script></html>`;
await writeFile(path.join(output,'index.html'),html,{flag:'wx'});
console.log(JSON.stringify({output,observations:manifest.rows.length,comparisons:manifest.comparisons.length,readyForFreeze:false}));
