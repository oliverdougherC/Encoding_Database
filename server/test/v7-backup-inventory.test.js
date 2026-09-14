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
