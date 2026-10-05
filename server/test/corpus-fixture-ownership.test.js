import test from 'node:test';
import assert from 'node:assert/strict';
import { removeCorpusFixture, readSettledCorpus } from './fixtures/corpus-postgres.mjs';

test('corpus cleanup retires only its exact owned protocol, not another active fixture', async () => {
  const protocols = [{id:'corpus-test-owner-protocol',state:'ACTIVE'}, {id:'corpus-test-owner-sibling-protocol',state:'ACTIVE'}];
  const db = { benchmarkProtocol: { updateMany: async ({where,data}) => {
    for (const protocol of protocols) {
      const matches = typeof where.id === 'string' ? protocol.id === where.id : protocol.id.startsWith(where.id.startsWith);
      if (matches) protocol.state = data.state;
    }
  } } };
  await removeCorpusFixture(db,'corpus-test-owner');
  assert.deepEqual(protocols.map(row=>row.state), ['RETIRED','ACTIVE']);
});

test('corpus cleanup requires explicit non-shared fixture ownership before a database mutation', async () => {
  let writes = 0;
  const db = { benchmarkProtocol:{ updateMany:async()=>{writes++;} } };
  for (const prefix of [undefined,'','corpus-test']) await assert.rejects(removeCorpusFixture(db,prefix), /explicit|owned|prefix/i);
  assert.equal(writes,0);
});


test('fixture read settling retries only explicit projection-busy state', async () => {
  let calls = 0;
  assert.equal(await readSettledCorpus(async () => {
    calls++;
    if (calls === 1) throw Object.assign(new Error('peer mutation'), {code:'CORPUS_REBUILD_PENDING'});
    return 'settled';
  }), 'settled');
  assert.equal(calls, 2);
  calls = 0;
  const failure = Object.assign(new Error('unexpected database failure'), {code:'P2010'});
  await assert.rejects(readSettledCorpus(async () => { calls++; throw failure; }), error => error === failure);
  assert.equal(calls, 1);
});
