WITH expected AS (
SELECT "environmentId", id AS "benchmarkRunId" FROM "BenchmarkRun"
WHERE "repetitionGroupId" LIKE '%-stable-%' OR "repetitionGroupId" LIKE '%-arrival-%'
), actual AS (
SELECT d."environmentId", m."benchmarkRunId" FROM "DerivedResultMember" m
JOIN "DerivedResult" d ON d.id = m."derivedResultId"
), missing AS (SELECT * FROM expected EXCEPT SELECT * FROM actual), unexpected AS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
SELECT json_build_object('expectedMemberCount',(SELECT count(*) FROM expected),'actualMemberCount',(SELECT count(*) FROM actual),'missingMembers',(SELECT count(*) FROM missing),'unexpectedMembers',(SELECT count(*) FROM unexpected),'derivedCohorts',(SELECT count(DISTINCT "environmentId") FROM actual),'pendingInvalidatingRows',(SELECT count(*) FROM "BenchmarkRun" WHERE id LIKE '%invalidating-extra%'),'dirtyPublicGroups',(SELECT count(*) FROM "PublicCorpusDirtyGroup"));
