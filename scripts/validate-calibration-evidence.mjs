#!/usr/bin/env node

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, '..');
const serverRoot = path.join(repoRoot, 'server');
const args = process.argv.slice(2);
const input = args.find((value) => !value.startsWith('--'));
const allowDraft = args.includes('--allow-draft');
if (!input) throw new Error('Usage: validate-calibration-evidence.mjs FILE [--allow-draft]');

const calibration = await import(path.join(serverRoot, 'dist', 'v7', 'calibration.js'));
const document = calibration.parseCalibrationEvidence(readFileSync(path.resolve(process.cwd(), input), 'utf8'));
const assessment = calibration.assessCalibrationEvidence(document);
process.stdout.write(`${JSON.stringify(assessment, null, 2)}\n`);
if (!assessment.readyForProductionFreeze && !allowDraft) process.exitCode = 1;
