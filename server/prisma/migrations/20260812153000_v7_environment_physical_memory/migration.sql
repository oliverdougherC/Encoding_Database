ALTER TABLE "Environment"
ADD COLUMN "physicalMemoryBytes" BIGINT;

UPDATE "Environment"
SET "physicalMemoryBytes" = ("canonicalJson"->>'physicalMemoryBytes')::BIGINT
WHERE "physicalMemoryBytes" IS NULL
  AND "canonicalJson" ? 'physicalMemoryBytes'
  AND ("canonicalJson"->>'physicalMemoryBytes') IS NOT NULL
  AND ("canonicalJson"->>'physicalMemoryBytes') <> '';
