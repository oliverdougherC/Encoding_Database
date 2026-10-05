#!/usr/bin/env node
// Create a separately sealed, auditable metadata representation. Never edits source DBs/snapshots.
import { readFile, mkdir, copyFile, writeFile, stat } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { canonicalJsonString, sha256Hex } from '../server/dist/v7/persistence.js';
import { receiptWallTimesEqual, receiptsEquivalent, CANONICAL_MEASUREMENT_RULES } from '../server/dist/v7/measurementGroup.js';
import { validationRecipeRules } from './calibration-validation-protocol.mjs';
import { validationMeasurementGroup, assertObservedValidationCpu } from './validation-measurement-group.mjs';
const hash = value => sha256Hex(canonicalJsonString(value));
const requireValue = (condition, message) => { if (!condition) throw new Error(message); };

export function repairValidationProtocolSnapshot(snapshot, receipts) {
  const { snapshotHash, ...originalPayload } = snapshot;
  requireValue(snapshot.schemaVersion === 'encodingdb-calibration-evidence-snapshot/v1' && hash(originalPayload) === snapshotHash, 'Source snapshot seal differs');
  const result = structuredClone(snapshot); const bindings = new Map(); const receiptProofs = [];
  for (const { document, sha256, originalPath } of receipts) {
    requireValue(/^[a-f0-9]{64}$/.test(sha256) && typeof originalPath === 'string', 'Missing audited campaign receipt identity');
    requireValue(document.schemaVersion === 'encodingdb-controlled-validation-campaign/v1' && document.validationOnly === true, 'Not original validation-only evidence');
    const rules = validationRecipeRules(document);
    requireValue(hash(document.source) === document.sourceRegistrationHash, 'Source registration differs');
    const environment = hash({ hardware: document.hardware, runtime: document.runtime, execution: document.execution, osName: document.osName, osVersion: document.osVersion });
    for (const group of document.campaign.recipeResults) {
      requireValue(group.stability.stable && group.runs.filter(run => run.schedule.phase === 'warmup').length === 1, 'Original group did not complete its declared warmup/stability');
      const measurementGroup = validationMeasurementGroup(group);
      const times = measurementGroup.countedAttempts.map(attempt => attempt.encodeWallTimeMs);
      const mean = times.reduce((a,b) => a+b,0)/times.length;
      requireValue((Math.max(...times)-Math.min(...times))/mean <= CANONICAL_MEASUREMENT_RULES.stabilityThresholdRatio, 'Original measured spread exceeds canonical gate');
      const ids = group.runs.filter(run => run.countedForStability).map(record => `validation_${hash(record.schedule)}`);
      requireValue(ids.every(id => snapshot.tables.runs.some(run => run.id === id)), 'Snapshot omits a counted group member');
      for (const record of group.runs.filter(run => run.countedForStability)) {
        assertObservedValidationCpu(record);
        const id = `validation_${hash(record.schedule)}`;
        requireValue(!bindings.has(id), 'Duplicate original measurement binding');
        bindings.set(id, { record, measurementGroup, document, environment, rules });
      }
    }
    receiptProofs.push({ originalPath, sha256, sourceRegistrationHash: document.sourceRegistrationHash, protocolConfigHash: hash(document.protocolConfig) });
  }
  const aliases = []; const runProofs = [];
  for (const protocol of result.tables.protocols) {
    requireValue(protocol.protocolVersion === '7.1' && protocol.sourceSuiteVersion === 'encodingdb-validation-holdouts-v1', 'Repair is restricted to the known validation-only namespace');
    const runs = result.tables.runs.filter(run => run.benchmarkProtocolId === protocol.id);
    requireValue(runs.length > 0 && runs.every(run => bindings.has(run.id)), 'Every repaired run needs an audited original campaign');
    const expected = bindings.get(runs[0].id).rules; const before = structuredClone(protocol.canonicalRecipeRules);
    requireValue(Object.keys(before).every(key => Object.hasOwn(expected,key) && before[key] === expected[key]), 'Conflicting existing rule cannot be repaired');
    requireValue(before.validationOnly === true && before.warmupRuns === 1 && before.minimumMeasuredRuns === 2, 'Not the known incomplete importer metadata');
    requireValue(hash(before) !== hash(expected), 'Protocol already complete; no metadata repair required');
    const oldId = protocol.id; const newId = `calibration_protocol_${hash({ oldId, rules: expected })}`;
    for (const run of runs) {
      const binding = bindings.get(run.id); const { record, measurementGroup, document } = binding;
      requireValue(hash(binding.rules) === hash(expected), 'Campaigns declare differing rules');
      const recipe = result.tables.recipes.find(row => row.id === run.recipeId);
      const environment = result.tables.environments.find(row => row.id === run.environmentId);
      const source = result.tables.clips.find(row => row.id === run.testClipId);
      const info = record.metadata.info;
      requireValue(recipe?.fingerprint === hash(JSON.parse(info.effectiveRecipeJson)) && environment?.fingerprint === binding.environment, 'Original recipe/environment identity differs');
      requireValue(source?.sha256 === document.source.sourceSha256 && run.inputHash === source.sha256 && source.suiteVersion === protocol.sourceSuiteVersion && run.workloadId === document.source.workloadId, 'Original source/workload identity differs');
      requireValue(run.physicalSourceId === document.physicalSourceId && run.encodeTimerBoundary === 'ffmpeg-process-v1' && info.encodeTimerBoundary === 'ffmpeg-process-v1', 'Physical source or timing boundary differs');
      requireValue(run.campaignId === record.schedule.campaign_id && run.repetitionIndex === record.schedule.repetition_index && run.repetitionGroupId === measurementGroup.repetitionGroupId && receiptsEquivalent(run.preRunEnvironmentCheck?.measurementGroup, measurementGroup), 'Original counted group binding differs');
      const timing = record.timing;
      requireValue(Math.abs((timing.end_monotonic_ns-timing.start_monotonic_ns)/1e9-timing.elapsed_s) <= 0.000001, 'Original monotonic timing differs');
      requireValue(run.sourceFps === timing.source_fps && receiptWallTimesEqual(run.encodeFps, timing.encode_fps) && receiptWallTimesEqual(run.realTimeRatio, timing.realtime_multiple), 'Original derived timing values differ');
      requireValue(receiptWallTimesEqual(run.encodeWallTimeMs, timing.elapsed_s*1000) && run.sourceFrameCount === timing.source_frame_count && run.encodedFrameCount === timing.encoded_frame_count, 'Measured timing/frame identity differs');
      requireValue(result.tables.artifacts.some(a => a.benchmarkRunId === run.id && a.role === 'ENCODED' && a.sha256 === info.artifactSha256), 'Encoded artifact identity differs');
      // The original importer hashes these exact fields; protocol database FK is NOT included.
      const immutable = { schedule: record.schedule, timing, measurementGroup, recipe: recipe.fingerprint, environment: environment.fingerprint, source: hash(document.source), physicalSourceId: document.physicalSourceId, artifact: info.artifactSha256 };
      requireValue(run.payloadHash === hash(immutable) && run.immutablePayloadHash === hash(immutable), 'Original measured payload hash does not verify');
      const beforeHash = hash(run); run.benchmarkProtocolId = newId;
      runProofs.push({ runId: run.id, beforeHash, afterHash: hash(run), preservedPayloadHash: run.payloadHash, changedFields: ['benchmarkProtocolId'] });
    }
    protocol.id = newId; protocol.canonicalRecipeRules = expected;
    aliases.push({ originalProtocolId: oldId, derivedProtocolId: newId, originalRules: before, derivedRules: expected, originalRuleHash: hash(before), derivedRuleHash: hash(expected) });
  }
  requireValue(bindings.size === result.tables.runs.length, 'Extra receipt membership is not represented by this snapshot');
  result.protocolMetadataRepair = { schemaVersion: 'encodingdb-validation-protocol-metadata-repair/v1', sourceSnapshotHash: snapshotHash, reason: 'Importer omitted predeclared maxAdaptiveRepeats/stabilityThresholdRatio; original campaign receipts prove unchanged measurement rules', protocolAliases: aliases, campaignReceipts: receiptProofs.sort((a,b)=>a.sha256.localeCompare(b.sha256)), runAliases: runProofs.sort((a,b)=>a.runId.localeCompare(b.runId)), unchangedAnalysisTableHash: hash(snapshot.tables.analyses), unchangedArtifactTableHash: hash(snapshot.tables.artifacts), payloadHashContract: 'Recomputed from original schedule,timing,counted measurement group,recipe fingerprint,environment fingerprint,source registration,physical source and artifact SHA. Database protocol FK is absent from this original contract.' };
  const { snapshotHash: _old, ...payload } = result; result.snapshotHash = hash(payload);
  return result;
}

async function fileHash(file) { const h=createHash('sha256');for await(const part of createReadStream(file))h.update(part);return h.digest('hex'); }
async function main() {
  const flags=new Map();for(let i=2;i<process.argv.length;i+=2)flags.set(process.argv[i],process.argv[i+1]);
  for(const flag of ['--snapshot','--receipts','--output'])requireValue(flags.has(flag),`${flag} is required`);
  const source=path.resolve(flags.get('--snapshot')),output=path.resolve(flags.get('--output'));
  const snapshot=JSON.parse(await readFile(path.join(source,'snapshot.json'),'utf8'));
  const descriptors=JSON.parse(await readFile(flags.get('--receipts'),'utf8'));const receipts=[];
  for(const entry of descriptors){const bytes=await readFile(entry.path);requireValue(sha256Hex(bytes)===entry.sha256,'Original campaign receipt differs from audited SHA');receipts.push({document:JSON.parse(bytes),sha256:entry.sha256,originalPath:entry.path});}
  const repaired=repairValidationProtocolSnapshot(snapshot,receipts);
  await mkdir(output);await mkdir(path.join(output,'objects'));
  for(const object of snapshot.objects){requireValue(/^[a-f0-9]{64}$/.test(object.sha256),'Invalid retained object SHA');const original=path.join(source,'objects',object.sha256);requireValue((await stat(original)).size===object.byteSize&&await fileHash(original)===object.sha256,'Source retained object differs');const destination=path.join(output,'objects',object.sha256);await copyFile(original,destination);requireValue(await fileHash(destination)===object.sha256,'Copied retained object differs');}
  await writeFile(path.join(output,'snapshot.json'),JSON.stringify(repaired,null,2)+'\n',{flag:'wx'});
  await writeFile(path.join(output,'protocol-repair.json'),JSON.stringify(repaired.protocolMetadataRepair,null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({sourceSnapshotHash:snapshot.snapshotHash,derivedSnapshotHash:repaired.snapshotHash,runCount:repaired.tables.runs.length,protocolAliases:repaired.protocolMetadataRepair.protocolAliases}));
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href)main().catch(error=>{console.error(error.message);process.exitCode=1;});
