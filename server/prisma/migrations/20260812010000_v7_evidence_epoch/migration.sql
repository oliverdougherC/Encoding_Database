CREATE TYPE "RateControlMode" AS ENUM ('CRF', 'CQ', 'ICQ', 'CQP', 'QP', 'VBR', 'CBR', 'ABR', 'OTHER');
CREATE TYPE "BenchmarkProtocolState" AS ENUM ('DRAFT', 'ACTIVE', 'RETIRED');
CREATE TYPE "BenchmarkRunStatus" AS ENUM ('PENDING', 'ACCEPTED', 'REJECTED', 'SUSPECT', 'INVALID');
CREATE TYPE "ArtifactRole" AS ENUM ('ENCODED', 'METADATA', 'TELEMETRY', 'LOG', 'ANALYSIS_REPORT');
CREATE TYPE "ArtifactStorageState" AS ENUM ('PENDING', 'UPLOADED', 'VERIFIED', 'RETAINED', 'DELETED', 'FAILED');
CREATE TYPE "QualityAnalysisStatus" AS ENUM ('PENDING', 'COMPLETE', 'SUSPECT', 'REJECTED', 'FAILED');
CREATE TYPE "DerivedResultKind" AS ENUM ('CLIP', 'WORKLOAD', 'GENERAL');
CREATE TYPE "EvidenceTier" AS ENUM ('PROVISIONAL', 'LOW', 'MEDIUM', 'HIGH');

CREATE TABLE "BenchmarkProtocol" (
  "id" TEXT NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  "protocolVersion" TEXT NOT NULL,
  "sourceSuiteVersion" TEXT NOT NULL,
  "minimumClientVersion" TEXT NOT NULL,
  "canonicalRecipeRules" JSONB NOT NULL,
  "canonicalOutputRules" JSONB NOT NULL,
  "metricWorkerVersion" TEXT NOT NULL,
  "state" "BenchmarkProtocolState" NOT NULL DEFAULT 'ACTIVE',
  "activatedAt" TIMESTAMP(3),
  "retiredAt" TIMESTAMP(3),

  CONSTRAINT "BenchmarkProtocol_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "TestClip" (
  "id" TEXT NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  "suiteId" TEXT NOT NULL,
  "suiteVersion" TEXT NOT NULL,
  "manifestVersion" TEXT NOT NULL,
  "clipKey" TEXT NOT NULL,
  "displayName" TEXT NOT NULL,
  "workloadId" TEXT NOT NULL,
  "contentClass" TEXT NOT NULL,
  "sourceProvenance" JSONB NOT NULL,
  "sha256" TEXT NOT NULL,
  "byteSize" INTEGER NOT NULL,
  "exactFrameCount" INTEGER NOT NULL,
  "exactDurationSeconds" DOUBLE PRECISION NOT NULL,
  "frameRateNumerator" INTEGER NOT NULL,
  "frameRateDenominator" INTEGER NOT NULL,
  "width" INTEGER NOT NULL,
  "height" INTEGER NOT NULL,
  "pixelFormat" TEXT NOT NULL,
  "bitDepth" INTEGER NOT NULL,
  "chromaSubsampling" TEXT NOT NULL,
  "colorPrimaries" TEXT,
  "transferCharacteristics" TEXT,
  "matrixCoefficients" TEXT,
  "colorRange" TEXT,
  "scanType" TEXT NOT NULL DEFAULT 'progressive',
  "hdrMetadata" JSONB,

  CONSTRAINT "TestClip_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "Recipe" (
  "id" TEXT NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  "fingerprint" TEXT NOT NULL,
  "canonicalJson" JSONB NOT NULL,
  "codecFamily" TEXT NOT NULL,
  "encoderImplementation" TEXT NOT NULL,
  "encoderVersion" TEXT,
  "preset" TEXT,
  "tune" TEXT,
  "profile" TEXT,
  "level" TEXT,
  "tier" TEXT,
  "pixelFormat" TEXT NOT NULL,
  "bitDepth" INTEGER NOT NULL,
  "chromaSubsampling" TEXT NOT NULL,
  "containerFormat" TEXT,
  "videoCodecTag" TEXT,
  "requestedRateControlMode" "RateControlMode" NOT NULL,
  "requestedQualityValue" DOUBLE PRECISION,
  "requestedTargetBitrateKbps" INTEGER,
  "requestedMaxBitrateKbps" INTEGER,
  "requestedBufferSizeKbits" INTEGER,
  "requestedQmin" INTEGER,
  "requestedQmax" INTEGER,
  "effectiveRateControlMode" "RateControlMode" NOT NULL,
  "effectiveQualityValue" DOUBLE PRECISION,
  "effectiveTargetBitrateKbps" INTEGER,
  "effectiveMaxBitrateKbps" INTEGER,
  "effectiveBufferSizeKbits" INTEGER,
  "effectiveQmin" INTEGER,
  "effectiveQmax" INTEGER,
  "requestedRateControl" JSONB NOT NULL,
  "effectiveRateControl" JSONB NOT NULL,
  "requestedOutputSettings" JSONB,
  "effectiveOutputSettings" JSONB,
  "normalizedRequestedOptions" JSONB,
  "normalizedEffectiveOptions" JSONB,
  "gopSize" INTEGER,
  "keyframeInterval" INTEGER,
  "bFrames" INTEGER,
  "frameReordering" BOOLEAN,
  "lookahead" INTEGER,
  "filmGrainSynthesis" JSONB,
  "majorTools" JSONB,

  CONSTRAINT "Recipe_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "Environment" (
  "id" TEXT NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  "fingerprint" TEXT NOT NULL,
  "canonicalJson" JSONB NOT NULL,
  "cpuModel" TEXT NOT NULL,
  "cpuArchitecture" TEXT NOT NULL,
  "physicalCoreCount" INTEGER,
  "logicalThreadCount" INTEGER,
  "gpuModel" TEXT,
  "selectedAcceleratorId" TEXT,
  "selectedAccelerator" TEXT,
  "driverVersion" TEXT,
  "osName" TEXT NOT NULL,
  "osVersion" TEXT NOT NULL,
  "ffmpegBuildFingerprint" TEXT NOT NULL,
  "ffmpegVersion" TEXT NOT NULL,
  "encoderVersion" TEXT,
  "clientVersion" TEXT NOT NULL,

  CONSTRAINT "Environment_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "BenchmarkRun" (
  "id" TEXT NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  "benchmarkProtocolId" TEXT NOT NULL,
  "testClipId" TEXT NOT NULL,
  "workloadId" TEXT NOT NULL,
  "recipeId" TEXT NOT NULL,
  "environmentId" TEXT NOT NULL,
  "payloadHash" TEXT NOT NULL,
  "inputHash" TEXT,
  "campaignId" TEXT,
  "repetitionGroupId" TEXT,
  "repetitionIndex" INTEGER,
  "encodeWallTimeMs" INTEGER,
  "encodeFps" DOUBLE PRECISION,
  "sourceFps" DOUBLE PRECISION,
  "realTimeRatio" DOUBLE PRECISION,
  "sourceFrameCount" INTEGER,
  "encodedFrameCount" INTEGER,
  "telemetry" JSONB,
  "telemetrySources" JSONB,
  "telemetryMissing" JSONB,
  "energyDomains" JSONB,
  "decodeBenchmark" JSONB,
  "preRunEnvironmentCheck" JSONB,
  "ffmpegProgressTelemetry" JSONB,
  "status" "BenchmarkRunStatus" NOT NULL DEFAULT 'PENDING',
  "statusReason" TEXT,
  "decidedAt" TIMESTAMP(3),

  CONSTRAINT "BenchmarkRun_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "Artifact" (
  "id" TEXT NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  "benchmarkRunId" TEXT NOT NULL,
  "role" "ArtifactRole" NOT NULL,
  "sha256" TEXT,
  "byteSize" INTEGER,
  "storageState" "ArtifactStorageState" NOT NULL DEFAULT 'PENDING',
  "storageProvider" TEXT,
  "storageBucket" TEXT,
  "storageKey" TEXT,
  "storageUrl" TEXT,
  "mediaContainer" TEXT,

  CONSTRAINT "Artifact_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "QualityAnalysis" (
  "id" TEXT NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  "benchmarkRunId" TEXT NOT NULL,
  "artifactId" TEXT,
  "status" "QualityAnalysisStatus" NOT NULL DEFAULT 'PENDING',
  "metricModelId" TEXT NOT NULL,
  "qualityContextId" TEXT,
  "analysisWorkerVersion" TEXT NOT NULL,
  "analysisProvenance" JSONB NOT NULL,
  "vmafMean" DOUBLE PRECISION,
  "vmafMedian" DOUBLE PRECISION,
  "vmafP1" DOUBLE PRECISION,
  "vmafP5" DOUBLE PRECISION,
  "vmafMin" DOUBLE PRECISION,
  "vmafMax" DOUBLE PRECISION,
  "vmafStdDev" DOUBLE PRECISION,
  "vmafHarmonicMean" DOUBLE PRECISION,
  "worstFrameIndex" INTEGER,
  "worstFrameTimestampMs" INTEGER,
  "belowThresholdFractions" JSONB,
  "vmafDistribution" JSONB,
  "xpsnr" DOUBLE PRECISION,
  "ssim" DOUBLE PRECISION,
  "psnr" DOUBLE PRECISION,
  "videoBitrateBps" DOUBLE PRECISION,
  "containerBitrateBps" DOUBLE PRECISION,
  "fileSizeBytes" INTEGER,

  CONSTRAINT "QualityAnalysis_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "ScoreContext" (
  "id" TEXT NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  "benchmarkProtocolId" TEXT NOT NULL,
  "formulaVersion" TEXT NOT NULL,
  "contextVersion" TEXT NOT NULL,
  "workloadId" TEXT NOT NULL,
  "qualityModelId" TEXT NOT NULL,
  "workloadReferenceBitrateBps" DOUBLE PRECISION NOT NULL,
  "transformConstants" JSONB NOT NULL,
  "referenceFrontier" JSONB,

  CONSTRAINT "ScoreContext_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "DerivedResult" (
  "id" TEXT NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  "kind" "DerivedResultKind" NOT NULL,
  "scopeKey" TEXT NOT NULL,
  "benchmarkProtocolId" TEXT NOT NULL,
  "workloadId" TEXT NOT NULL,
  "testClipId" TEXT,
  "recipeId" TEXT NOT NULL,
  "environmentId" TEXT NOT NULL,
  "scoreContextId" TEXT NOT NULL,
  "aggregatorVersion" TEXT NOT NULL,
  "acceptedRunCount" INTEGER NOT NULL,
  "suspectRunCount" INTEGER NOT NULL DEFAULT 0,
  "rejectedRunCount" INTEGER NOT NULL DEFAULT 0,
  "invalidRunCount" INTEGER NOT NULL DEFAULT 0,
  "repetitionCount" INTEGER NOT NULL,
  "centerEncodeFps" DOUBLE PRECISION,
  "centerRealTimeRatio" DOUBLE PRECISION,
  "centerVideoBitrateBps" DOUBLE PRECISION,
  "centerFileSizeBytes" DOUBLE PRECISION,
  "centerVmafMean" DOUBLE PRECISION,
  "centerVmafP5" DOUBLE PRECISION,
  "plQuality" DOUBLE PRECISION,
  "plBitrate" DOUBLE PRECISION,
  "plSpeed" DOUBLE PRECISION,
  "plTotal" DOUBLE PRECISION,
  "confidenceLower" DOUBLE PRECISION,
  "confidenceUpper" DOUBLE PRECISION,
  "evidenceTier" "EvidenceTier" NOT NULL DEFAULT 'PROVISIONAL',
  "evidenceSummary" JSONB NOT NULL,
  "confidenceIntervals" JSONB NOT NULL,
  "dispersion" JSONB NOT NULL,
  "recomputationSpec" JSONB NOT NULL,

  CONSTRAINT "DerivedResult_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "DerivedResultMember" (
  "id" TEXT NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "derivedResultId" TEXT NOT NULL,
  "benchmarkRunId" TEXT NOT NULL,

  CONSTRAINT "DerivedResultMember_pkey" PRIMARY KEY ("id")
);

ALTER TABLE "BenchmarkRun"
  ADD CONSTRAINT "BenchmarkRun_benchmarkProtocolId_fkey"
  FOREIGN KEY ("benchmarkProtocolId") REFERENCES "BenchmarkProtocol"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "BenchmarkRun"
  ADD CONSTRAINT "BenchmarkRun_testClipId_fkey"
  FOREIGN KEY ("testClipId") REFERENCES "TestClip"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "BenchmarkRun"
  ADD CONSTRAINT "BenchmarkRun_recipeId_fkey"
  FOREIGN KEY ("recipeId") REFERENCES "Recipe"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "BenchmarkRun"
  ADD CONSTRAINT "BenchmarkRun_environmentId_fkey"
  FOREIGN KEY ("environmentId") REFERENCES "Environment"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "Artifact"
  ADD CONSTRAINT "Artifact_benchmarkRunId_fkey"
  FOREIGN KEY ("benchmarkRunId") REFERENCES "BenchmarkRun"("id") ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE "QualityAnalysis"
  ADD CONSTRAINT "QualityAnalysis_benchmarkRunId_fkey"
  FOREIGN KEY ("benchmarkRunId") REFERENCES "BenchmarkRun"("id") ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE "QualityAnalysis"
  ADD CONSTRAINT "QualityAnalysis_artifactId_fkey"
  FOREIGN KEY ("artifactId") REFERENCES "Artifact"("id") ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE "ScoreContext"
  ADD CONSTRAINT "ScoreContext_benchmarkProtocolId_fkey"
  FOREIGN KEY ("benchmarkProtocolId") REFERENCES "BenchmarkProtocol"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "DerivedResult"
  ADD CONSTRAINT "DerivedResult_benchmarkProtocolId_fkey"
  FOREIGN KEY ("benchmarkProtocolId") REFERENCES "BenchmarkProtocol"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "DerivedResult"
  ADD CONSTRAINT "DerivedResult_testClipId_fkey"
  FOREIGN KEY ("testClipId") REFERENCES "TestClip"("id") ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE "DerivedResult"
  ADD CONSTRAINT "DerivedResult_recipeId_fkey"
  FOREIGN KEY ("recipeId") REFERENCES "Recipe"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "DerivedResult"
  ADD CONSTRAINT "DerivedResult_environmentId_fkey"
  FOREIGN KEY ("environmentId") REFERENCES "Environment"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "DerivedResult"
  ADD CONSTRAINT "DerivedResult_scoreContextId_fkey"
  FOREIGN KEY ("scoreContextId") REFERENCES "ScoreContext"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "DerivedResultMember"
  ADD CONSTRAINT "DerivedResultMember_derivedResultId_fkey"
  FOREIGN KEY ("derivedResultId") REFERENCES "DerivedResult"("id") ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE "DerivedResultMember"
  ADD CONSTRAINT "DerivedResultMember_benchmarkRunId_fkey"
  FOREIGN KEY ("benchmarkRunId") REFERENCES "BenchmarkRun"("id") ON DELETE CASCADE ON UPDATE CASCADE;

CREATE UNIQUE INDEX "BenchmarkProtocol_protocolVersion_sourceSuiteVersion_metricWorkerVersion_key"
  ON "BenchmarkProtocol"("protocolVersion", "sourceSuiteVersion", "metricWorkerVersion");
CREATE INDEX "BenchmarkProtocol_state_idx" ON "BenchmarkProtocol"("state");

CREATE UNIQUE INDEX "TestClip_sha256_key" ON "TestClip"("sha256");
CREATE UNIQUE INDEX "TestClip_suiteId_suiteVersion_clipKey_key" ON "TestClip"("suiteId", "suiteVersion", "clipKey");
CREATE INDEX "TestClip_workloadId_idx" ON "TestClip"("workloadId");
CREATE INDEX "TestClip_contentClass_idx" ON "TestClip"("contentClass");

CREATE UNIQUE INDEX "Recipe_fingerprint_key" ON "Recipe"("fingerprint");
CREATE INDEX "Recipe_codecFamily_encoderImplementation_preset_idx"
  ON "Recipe"("codecFamily", "encoderImplementation", "preset");

CREATE UNIQUE INDEX "Environment_fingerprint_key" ON "Environment"("fingerprint");
CREATE INDEX "Environment_cpuModel_idx" ON "Environment"("cpuModel");
CREATE INDEX "Environment_gpuModel_idx" ON "Environment"("gpuModel");

CREATE UNIQUE INDEX "BenchmarkRun_payloadHash_key" ON "BenchmarkRun"("payloadHash");
CREATE INDEX "BenchmarkRun_benchmarkProtocolId_workloadId_recipeId_environmentId_status_idx"
  ON "BenchmarkRun"("benchmarkProtocolId", "workloadId", "recipeId", "environmentId", "status");
CREATE INDEX "BenchmarkRun_repetitionGroupId_idx" ON "BenchmarkRun"("repetitionGroupId");

CREATE UNIQUE INDEX "Artifact_benchmarkRunId_role_key" ON "Artifact"("benchmarkRunId", "role");
CREATE INDEX "Artifact_storageState_idx" ON "Artifact"("storageState");
CREATE INDEX "Artifact_sha256_idx" ON "Artifact"("sha256");

CREATE UNIQUE INDEX "QualityAnalysis_benchmarkRunId_metricModelId_analysisWorkerVersion_key"
  ON "QualityAnalysis"("benchmarkRunId", "metricModelId", "analysisWorkerVersion");
CREATE INDEX "QualityAnalysis_status_idx" ON "QualityAnalysis"("status");

CREATE UNIQUE INDEX "ScoreContext_formulaVersion_contextVersion_workloadId_qualityModelId_key"
  ON "ScoreContext"("formulaVersion", "contextVersion", "workloadId", "qualityModelId");
CREATE INDEX "ScoreContext_benchmarkProtocolId_idx" ON "ScoreContext"("benchmarkProtocolId");

CREATE UNIQUE INDEX "DerivedResult_kind_benchmarkProtocolId_recipeId_environmentId_scoreContextId_scopeKey_key"
  ON "DerivedResult"("kind", "benchmarkProtocolId", "recipeId", "environmentId", "scoreContextId", "scopeKey");
CREATE INDEX "DerivedResult_workloadId_idx" ON "DerivedResult"("workloadId");
CREATE INDEX "DerivedResult_evidenceTier_idx" ON "DerivedResult"("evidenceTier");

CREATE UNIQUE INDEX "DerivedResultMember_derivedResultId_benchmarkRunId_key"
  ON "DerivedResultMember"("derivedResultId", "benchmarkRunId");
CREATE INDEX "DerivedResultMember_benchmarkRunId_idx" ON "DerivedResultMember"("benchmarkRunId");

ALTER TABLE "Benchmark"
  DROP CONSTRAINT IF EXISTS "Benchmark_v7_aggregate_key";
