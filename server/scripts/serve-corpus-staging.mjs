#!/usr/bin/env node
// Disposable loopback-only HTTP surface for the isolated metadata load harness.
import { assertIsolatedCorpusDatabase } from '../test/fixtures/corpus-postgres.mjs';
assertIsolatedCorpusDatabase(process.env.DATABASE_URL);
const { default: express } = await import('express');
const { default: routes } = await import('../dist/routes.js');
const { prisma } = await import('../dist/db.js');
const { startPublicCorpusRefreshLoop, publicCorpusReadiness } = await import('../dist/v7/corpusQuery.js');
const stopRefresh = startPublicCorpusRefreshLoop(prisma);
const app = express();
app.get('/health/corpus', async (_req, res) => {
  const state = await publicCorpusReadiness(prisma);
  res.status(state.ready ? 200 : 503).json(state);
});
app.use(express.json({ limit: '1mb' }));
app.use(routes);
const server = app.listen(Number(process.env.CORPUS_STAGING_PORT ?? 3081), '127.0.0.1', () => {
  console.log(`Isolated corpus staging: http://127.0.0.1:${server.address().port}`);
});
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => { stopRefresh(); server.close(() => process.exit(0)); });
