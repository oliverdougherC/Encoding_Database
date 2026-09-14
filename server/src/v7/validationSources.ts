import { readFileSync } from 'node:fs';
import { canonicalJsonString, sha256Hex } from './persistence.js';
import { loadAuthoritativeSuiteManifest } from './suite.js';

export const VALIDATION_SOURCE_SUITE = 'encodingdb-validation-holdouts-v1';
export interface ValidationSourceRegistration {
  sourceSuiteVersion: typeof VALIDATION_SOURCE_SUITE;
  workloadId: string;
  sourceSha256: string;
  sourceGroupId: string;
  sceneGroupId: string;
  firstSourceFrame: number;
  endSourceFrameExclusive: number;
  sourceFrameRate: string;
  contentClass: string;
  frameCount: number;
  durationSeconds: number;
  byteSize: number;
  width: 1920;
  height: 1080;
  pixelFormat: 'yuv420p';
  frameRate: '24/1';
  normalization: string;
  sourceEvidenceHash: string;
}

export function validationSourceHash(source: ValidationSourceRegistration): string {
  return sha256Hex(canonicalJsonString(source as never));
}

export function loadRegisteredValidationSource(workloadId: string, file = process.env.VALIDATION_SOURCE_REGISTRY_PATH): ValidationSourceRegistration {
  if (!file) throw new Error('Validation-only evidence requires an operator-installed source registry');
  const registry = JSON.parse(readFileSync(file, 'utf8'));
  const { registryHash, ...payload } = registry;
  if (registry.schemaVersion !== 'encodingdb-validation-source-registry/v1' || registryHash !== sha256Hex(canonicalJsonString(payload))) throw new Error('Validation source registry hash mismatch');
  const sources = registry.sources as ValidationSourceRegistration[];
  const matches = sources.filter((entry) => entry.workloadId === workloadId);
  if (matches.length !== 1) throw new Error('Validation source must have one immutable registration');
  const source = matches[0]!;
  const frozen = loadAuthoritativeSuiteManifest();
  const nativeRate = /^(\d+)\/(\d+)$/.exec(source.sourceFrameRate);
  const nativeFps = nativeRate && Number(nativeRate[2]) > 0 ? Number(nativeRate[1]) / Number(nativeRate[2]) : 0;
  if (source.sourceSuiteVersion !== VALIDATION_SOURCE_SUITE || !source.workloadId.startsWith('validation-')
    || frozen.clips.some((clip) => clip.id === source.workloadId || clip.sha256 === source.sourceSha256)
    || !/^[0-9a-f]{64}$/.test(source.sourceSha256) || !/^[0-9a-f]{64}$/.test(source.sourceEvidenceHash)
    || !source.sourceGroupId || !source.sceneGroupId || !Number.isInteger(source.firstSourceFrame) || !Number.isInteger(source.endSourceFrameExclusive)
    || source.firstSourceFrame < 0 || source.endSourceFrameExclusive <= source.firstSourceFrame
    || nativeFps <= 0 || source.endSourceFrameExclusive - source.firstSourceFrame !== Math.ceil(source.durationSeconds * nativeFps)
    || source.frameRate !== '24/1' || source.width !== 1920 || source.height !== 1080 || source.pixelFormat !== 'yuv420p'
    || source.durationSeconds < 30 || source.durationSeconds > 60 || source.frameCount !== source.durationSeconds * 24) {
    throw new Error('Invalid validation source registration or attempted frozen-source substitution');
  }
  return source;
}
