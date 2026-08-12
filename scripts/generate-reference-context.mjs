import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..');
const serverRoot = path.join(repoRoot, 'server');

function parseArgs(argv) {
  const flags = new Map();
  const positional = [];
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token.startsWith('--')) {
      const next = argv[index + 1];
      if (next && !next.startsWith('--')) {
        flags.set(token, next);
        index += 1;
      } else {
        flags.set(token, 'true');
      }
      continue;
    }
    positional.push(token);
  }
  return { flags, positional };
}

const { flags, positional } = parseArgs(process.argv.slice(2));
const sweepPath = positional[0]
  ? path.resolve(process.cwd(), positional[0])
  : path.join(serverRoot, 'config', 'reference-sweeps', 'test-only.synthetic.encodingdb-test-suite-v1.vmaf-v1-sdr-sd.json');
const outputPath = positional[1]
  ? path.resolve(process.cwd(), positional[1])
  : path.join(serverRoot, 'config', 'reference-contexts', 'test-only.synthetic.encodingdb-test-suite-v1.vmaf-v1-sdr-sd.context.json');

const referenceContextModule = await import(path.join(serverRoot, 'dist', 'v7', 'referenceContext.js'));
let context;

if (flags.has('--benchmark-protocol-id')) {
  const { prisma } = await import(path.join(serverRoot, 'dist', 'db.js'));
  try {
    context = await referenceContextModule.generateReferenceContextFromDatabase(prisma, {
      benchmarkProtocolId: flags.get('--benchmark-protocol-id'),
      benchmarkProtocolVersion: flags.get('--benchmark-protocol-version'),
      sourceSuiteVersion: flags.get('--source-suite-version'),
      qualityModelId: flags.get('--quality-model-id'),
      contextVersion: flags.get('--context-version'),
      formulaVersion: flags.get('--formula-version') ?? '7.0',
      targetMetricValue: flags.has('--target-metric-value') ? Number(flags.get('--target-metric-value')) : undefined,
      qualityExponent: flags.has('--quality-exponent') ? Number(flags.get('--quality-exponent')) : undefined,
      speedCurveRate: flags.has('--speed-curve-rate') ? Number(flags.get('--speed-curve-rate')) : undefined,
      speedSaturationRealtime: flags.has('--speed-saturation-realtime') ? Number(flags.get('--speed-saturation-realtime')) : undefined,
    });
  } finally {
    await prisma.$disconnect().catch(() => {});
  }
} else {
  const sweep = JSON.parse(readFileSync(sweepPath, 'utf8'));
  context = referenceContextModule.buildReferenceContextFromSweep(sweep);
}

if (flags.has('--calibration-evidence')) {
  if (!flags.has('--benchmark-protocol-id')) {
    throw new Error('--calibration-evidence can only promote a context generated from retained database evidence');
  }
  const calibrationPath = path.resolve(process.cwd(), flags.get('--calibration-evidence'));
  const calibrationModule = await import(path.join(serverRoot, 'dist', 'v7', 'calibration.js'));
  const calibration = calibrationModule.parseCalibrationEvidence(readFileSync(calibrationPath, 'utf8'));
  context = referenceContextModule.activateReferenceContextForProduction(context, calibration);
}

mkdirSync(path.dirname(outputPath), { recursive: true });
writeFileSync(outputPath, `${JSON.stringify(context, null, 2)}\n`, 'utf8');
process.stdout.write(`${outputPath}\n`);
