import assert from 'node:assert/strict';
import test from 'node:test';
import { databaseInventory, verifyBackupInventory } from '../scripts/v7-backup-inventory.mjs';

test('new backup inventories bind the selected public analysis and membership hash', async () => {
  const group = { id: 'g', runId: 'r', artifactId: 'a', analysisId: 'q', accepted: 2, suspect: 1, repetitions: 2, acceptedMembershipHash: 'exact-members' };
  const current = await databaseInventory({ artifact: { findMany: async () => [] }, derivedResultMember: { findMany: async () => [] }, $queryRawUnsafe: async (sql) => sql.includes('to_regclass') ? [{ name: 'PublicCorpusGroup' }] : [group] });
  const expected = { evidenceVersion: 'encodingdb-v7-backup-inventory/v2', ...structuredClone(current) };
  verifyBackupInventory(current, expected);
  current.publicCorpusGroups[0].acceptedMembershipHash = 'different-members';
  assert.throws(() => verifyBackupInventory(current, expected), /membership hashes differ/);
  current.publicCorpusGroups[0].acceptedMembershipHash = 'exact-members';
  current.publicCorpusGroups[0].analysisId = 'different-analysis';
  assert.throws(() => verifyBackupInventory(current, expected), /selections/);
});

test('legacy backups remain verifiable without pretending they covered the new cache', async () => {
  const current = await databaseInventory({ artifact: { findMany: async () => [] }, derivedResultMember: { findMany: async () => [] }, $queryRawUnsafe: async () => [{ name: null }] });
  assert.deepEqual(current.publicCorpusGroups, []);
  verifyBackupInventory(current, { evidenceVersion: 'encodingdb-v7-backup-inventory/v1', artifacts: [], derivedMembers: [] });
});

import { parseEnvText, validateProductionEnv } from '../../scripts/validate-production-env.mjs';
import { readFileSync } from 'node:fs';
test('production cannot admit unlimited evidence or outgrow its protected backup envelope', () => {
  const defaults = parseEnvText(readFileSync(new URL('../env.example', import.meta.url), 'utf8'));
  const unlimited = validateProductionEnv({ env: { ...defaults, ARTIFACT_STORAGE_QUOTA_BYTES: '0' } });
  assert.ok(unlimited.errors.includes('ARTIFACT_STORAGE_QUOTA_BYTES must be a positive number'));
  const tooSmall = validateProductionEnv({ env: { ...defaults, V7_BACKUP_MAX_ARTIFACT_BYTES: String(10 * 1024 ** 3) } });
  assert.ok(tooSmall.errors.some((reason) => reason.includes('staging/filesystem headroom')));
  const protectedProfile = validateProductionEnv({ env: defaults });
  assert.ok(!protectedProfile.errors.some((reason) => reason.includes('ARTIFACT_STORAGE_QUOTA_BYTES') || reason.includes('V7_BACKUP_MAX_ARTIFACT_BYTES')));
});
