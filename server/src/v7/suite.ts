import { readFileSync } from 'node:fs';

import { z } from 'zod';

export const SUITE_V1_MANIFEST_PATH = new URL('../../resources/test_suite_v1/manifest.json', import.meta.url);
export const SUITE_V1_ID = 'encodingdb-test-suite' as const;
export const SUITE_V1_VERSION = 'encodingdb-test-suite-v1' as const;
export const SUITE_V1_GENERAL_WEIGHTING = 'equal-class-geometric-mean' as const;
export const SUITE_V1_LICENSE = 'CC0-1.0' as const;
export const SUITE_V1_DETERMINISTIC_FLAGS = [
  '-threads 1',
  '-fflags +bitexact',
  '-flags:v +bitexact',
  '-map_metadata -1',
  '-map_chapters -1',
] as const;
export const SUITE_V1_CANONICAL_CONTENT_CLASSES = [
  'high-motion-sports',
  'fine-natural-detail',
  'film-grain-noise',
  'dark-gradients-shadows',
  'animation-flat-fields',
  'screen-text',
  'talking-head',
] as const;

export type SuiteV1CanonicalContentClass = typeof SUITE_V1_CANONICAL_CONTENT_CLASSES[number];

const canonicalContentClassSchema = z.enum(SUITE_V1_CANONICAL_CONTENT_CLASSES);
const deterministicFlagsSchema = z.tuple([
  z.literal(SUITE_V1_DETERMINISTIC_FLAGS[0]),
  z.literal(SUITE_V1_DETERMINISTIC_FLAGS[1]),
  z.literal(SUITE_V1_DETERMINISTIC_FLAGS[2]),
  z.literal(SUITE_V1_DETERMINISTIC_FLAGS[3]),
  z.literal(SUITE_V1_DETERMINISTIC_FLAGS[4]),
]);

const rationalSchema = z.object({
  numerator: z.number().int().positive(),
  denominator: z.number().int().positive(),
}).strict();

const mediaSchema = z.object({
  frameCount: z.number().int().positive(),
  duration: rationalSchema,
  frameRate: rationalSchema,
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  pixelFormat: z.string().trim().min(1),
  bitDepth: z.number().int().positive(),
  chromaSubsampling: z.string().trim().min(1),
  colorPrimaries: z.string().trim().min(1),
  colorTransfer: z.string().trim().min(1),
  colorMatrix: z.string().trim().min(1),
  colorRange: z.string().trim().min(1),
  fieldOrder: z.string().trim().min(1),
  hdrMetadata: z.null(),
}).strict();

const suiteClipSchema = z.object({
  id: z.string().trim().min(1),
  displayName: z.string().trim().min(1),
  contentClass: canonicalContentClassSchema,
  payloadContentClass: z.string().trim().min(1),
  description: z.string().trim().min(1),
  fileName: z.string().trim().min(1),
  source: z.object({
    kind: z.literal('project-generated'),
    provenance: z.string().trim().min(1),
    license: z.literal(SUITE_V1_LICENSE),
  }).strict(),
  acquisition: z.object({
    kind: z.literal('generated'),
    ffmpegLavfi: z.string().trim().min(1),
    container: z.literal('mkv'),
    videoCodec: z.literal('ffv1'),
    deterministicFlags: deterministicFlagsSchema,
  }).strict(),
  media: mediaSchema,
  sha256: z.string().regex(/^[0-9a-f]{64}$/),
  byteSize: z.number().int().positive(),
}).strict();

const suiteManifestSchema = z.object({
  suiteId: z.literal(SUITE_V1_ID),
  suiteVersion: z.literal(SUITE_V1_VERSION),
  displayName: z.string().trim().min(1),
  manifestVersion: z.number().int().positive(),
  defaultQuickClipId: z.string().trim().min(1),
  requiredContentClasses: z.array(canonicalContentClassSchema),
  generalPlPolicy: z.object({
    requiresCompleteCoverage: z.literal(true),
    weighting: z.literal(SUITE_V1_GENERAL_WEIGHTING),
    legacySingleClipGeneralPlAllowed: z.literal(false),
  }).strict(),
  redistribution: z.object({
    license: z.literal(SUITE_V1_LICENSE),
    notes: z.string().trim().min(1),
  }).strict(),
  clips: z.array(suiteClipSchema),
}).strict().superRefine((manifest, ctx) => {
  if (manifest.requiredContentClasses.length !== SUITE_V1_CANONICAL_CONTENT_CLASSES.length) {
    ctx.addIssue({
      code: 'custom',
      path: ['requiredContentClasses'],
      message: `requiredContentClasses must contain exactly ${SUITE_V1_CANONICAL_CONTENT_CLASSES.length} canonical classes`,
    });
  }
  if (manifest.requiredContentClasses.join('|') !== SUITE_V1_CANONICAL_CONTENT_CLASSES.join('|')) {
    ctx.addIssue({
      code: 'custom',
      path: ['requiredContentClasses'],
      message: 'requiredContentClasses must match the canonical PL-v7 class order exactly',
    });
  }
  if (manifest.clips.length !== SUITE_V1_CANONICAL_CONTENT_CLASSES.length) {
    ctx.addIssue({
      code: 'custom',
      path: ['clips'],
      message: `clips must contain exactly ${SUITE_V1_CANONICAL_CONTENT_CLASSES.length} entries`,
    });
  }

  const clipIds = new Set<string>();
  const fileNames = new Set<string>();
  const clipHashes = new Set<string>();
  const classes = new Map<SuiteV1CanonicalContentClass, number>();

  for (const [index, clip] of manifest.clips.entries()) {
    if (clipIds.has(clip.id)) {
      ctx.addIssue({ code: 'custom', path: ['clips', index, 'id'], message: `duplicate clip id ${clip.id}` });
    }
    clipIds.add(clip.id);

    if (fileNames.has(clip.fileName)) {
      ctx.addIssue({ code: 'custom', path: ['clips', index, 'fileName'], message: `duplicate fileName ${clip.fileName}` });
    }
    fileNames.add(clip.fileName);

    if (clipHashes.has(clip.sha256)) {
      ctx.addIssue({ code: 'custom', path: ['clips', index, 'sha256'], message: `duplicate sha256 ${clip.sha256}` });
    }
    clipHashes.add(clip.sha256);

    classes.set(clip.contentClass, (classes.get(clip.contentClass) ?? 0) + 1);
  }

  for (const contentClass of SUITE_V1_CANONICAL_CONTENT_CLASSES) {
    const count = classes.get(contentClass) ?? 0;
    if (count !== 1) {
      ctx.addIssue({
        code: 'custom',
        path: ['clips'],
        message: `expected exactly one clip for canonical content class ${contentClass}; found ${count}`,
      });
    }
  }

  if (!clipIds.has(manifest.defaultQuickClipId)) {
    ctx.addIssue({
      code: 'custom',
      path: ['defaultQuickClipId'],
      message: `defaultQuickClipId ${manifest.defaultQuickClipId} does not match a declared clip`,
    });
  }
});

export type SuiteV1Manifest = z.infer<typeof suiteManifestSchema>;
export type SuiteV1ClipManifest = SuiteV1Manifest['clips'][number];

export interface PublicTestVideoCatalogEntry {
  suiteId: string;
  suiteVersion: string;
  manifestVersion: number;
  clipId: string;
  workloadId: string;
  displayName: string;
  contentClass: SuiteV1CanonicalContentClass;
  payloadContentClass: string;
  description: string;
  fileName: string;
  sha256: string;
  sizeBytes: number;
  source: SuiteV1ClipManifest['source'];
  acquisition: SuiteV1ClipManifest['acquisition'];
  media: SuiteV1ClipManifest['media'];
}

export interface SuiteTestClipRecordInput {
  suiteId: string;
  suiteVersion: string;
  manifestVersion: string;
  clipKey: string;
  displayName: string;
  workloadId: string;
  contentClass: SuiteV1CanonicalContentClass;
  sourceProvenance: {
    source: SuiteV1ClipManifest['source'];
    acquisition: SuiteV1ClipManifest['acquisition'];
    fileName: string;
    payloadContentClass: string;
    description: string;
    redistribution: SuiteV1Manifest['redistribution'];
  };
  sha256: string;
  byteSize: number;
  exactFrameCount: number;
  exactDurationSeconds: number;
  frameRateNumerator: number;
  frameRateDenominator: number;
  width: number;
  height: number;
  pixelFormat: string;
  bitDepth: number;
  chromaSubsampling: string;
  colorPrimaries: string;
  transferCharacteristics: string;
  matrixCoefficients: string;
  colorRange: string;
  scanType: string;
  hdrMetadata: null;
}

export interface SuiteTestClipUpsertArgs {
  where: {
    suiteId_suiteVersion_clipKey: {
      suiteId: string;
      suiteVersion: string;
      clipKey: string;
    };
  };
  create: SuiteTestClipRecordInput;
  update: SuiteTestClipRecordInput;
}

export interface TestClipUpsertDelegate {
  upsert(args: SuiteTestClipUpsertArgs): Promise<unknown>;
}

let cachedManifest: SuiteV1Manifest | null = null;

function rationalToFloat(value: { numerator: number; denominator: number }): number {
  return value.numerator / value.denominator;
}

export function parseSuiteManifest(input: unknown, sourceLabel = 'EncodingDB Test Suite v1 manifest'): SuiteV1Manifest {
  const parsed = suiteManifestSchema.safeParse(input);
  if (!parsed.success) {
    const issues = parsed.error.issues
      .map((issue) => `${issue.path.join('.') || '<root>'}: ${issue.message}`)
      .join('; ');
    throw new Error(`${sourceLabel} is invalid: ${issues}`);
  }
  return parsed.data;
}

export function loadAuthoritativeSuiteManifest(): SuiteV1Manifest {
  if (cachedManifest) {
    return cachedManifest;
  }
  const raw = JSON.parse(readFileSync(SUITE_V1_MANIFEST_PATH, 'utf8')) as unknown;
  cachedManifest = parseSuiteManifest(raw, String(SUITE_V1_MANIFEST_PATH));
  return cachedManifest;
}

export function buildPublicTestVideoCatalog(manifest: SuiteV1Manifest = loadAuthoritativeSuiteManifest()): readonly PublicTestVideoCatalogEntry[] {
  return manifest.clips.map((clip) => ({
    suiteId: manifest.suiteId,
    suiteVersion: manifest.suiteVersion,
    manifestVersion: manifest.manifestVersion,
    clipId: clip.id,
    workloadId: clip.id,
    displayName: clip.displayName,
    contentClass: clip.contentClass,
    payloadContentClass: clip.payloadContentClass,
    description: clip.description,
    fileName: clip.fileName,
    sha256: clip.sha256,
    sizeBytes: clip.byteSize,
    source: clip.source,
    acquisition: clip.acquisition,
    media: clip.media,
  }));
}

export function buildSuiteTestClipRecordInput(
  manifest: SuiteV1Manifest,
  clip: SuiteV1ClipManifest,
): SuiteTestClipRecordInput {
  return {
    suiteId: manifest.suiteId,
    suiteVersion: manifest.suiteVersion,
    manifestVersion: String(manifest.manifestVersion),
    clipKey: clip.id,
    displayName: clip.displayName,
    workloadId: clip.id,
    contentClass: clip.contentClass,
    sourceProvenance: {
      source: clip.source,
      acquisition: clip.acquisition,
      fileName: clip.fileName,
      payloadContentClass: clip.payloadContentClass,
      description: clip.description,
      redistribution: manifest.redistribution,
    },
    sha256: clip.sha256,
    byteSize: clip.byteSize,
    exactFrameCount: clip.media.frameCount,
    exactDurationSeconds: rationalToFloat(clip.media.duration),
    frameRateNumerator: clip.media.frameRate.numerator,
    frameRateDenominator: clip.media.frameRate.denominator,
    width: clip.media.width,
    height: clip.media.height,
    pixelFormat: clip.media.pixelFormat,
    bitDepth: clip.media.bitDepth,
    chromaSubsampling: clip.media.chromaSubsampling,
    colorPrimaries: clip.media.colorPrimaries,
    transferCharacteristics: clip.media.colorTransfer,
    matrixCoefficients: clip.media.colorMatrix,
    colorRange: clip.media.colorRange,
    scanType: clip.media.fieldOrder,
    hdrMetadata: clip.media.hdrMetadata,
  };
}

export function buildSuiteTestClipUpsertArgs(
  manifest: SuiteV1Manifest,
  clip: SuiteV1ClipManifest,
): SuiteTestClipUpsertArgs {
  const record = buildSuiteTestClipRecordInput(manifest, clip);
  return {
    where: {
      suiteId_suiteVersion_clipKey: {
        suiteId: record.suiteId,
        suiteVersion: record.suiteVersion,
        clipKey: record.clipKey,
      },
    },
    create: record,
    update: record,
  };
}

export async function upsertSuiteTestClips(
  testClipDelegate: TestClipUpsertDelegate,
  manifest: SuiteV1Manifest = loadAuthoritativeSuiteManifest(),
): Promise<readonly unknown[]> {
  const persisted: unknown[] = [];
  for (const clip of manifest.clips) {
    persisted.push(await testClipDelegate.upsert(buildSuiteTestClipUpsertArgs(manifest, clip)));
  }
  return persisted;
}
