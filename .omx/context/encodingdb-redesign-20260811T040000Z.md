# EncodingDB redesign context

## Task

Reposition the existing EncodingDB frontend as a calm public technical database of reproducible video encoding benchmarks.

## Desired outcome

The browse page places real result data first; navigation, visual tokens, filtering, selection/comparison, provenance, and reference pages use neutral database language and retain existing API compatibility.

## Evidence

- The frontend is Next.js 16/React 19 with existing server-side query pagination and virtualized table rendering.
- Existing `Benchmark` rows expose the requested raw metrics and provenance fields.
- Existing UI uses a desktop sidebar, Command Center/workspace copy, dashboard cards, and prominent PL Score controls.
- API routes proxy the existing backend; no backend migration is required for a frontend-first migration.

## Constraints

- Preserve query API and client/download flow.
- Do not use fake production benchmark data.
- Use URL-backed filters and local browser storage only for My Hardware/theme preference.
- Do not surface PL Score in the primary browse or comparison UI.

## Primary touchpoints

`frontend/app/page.tsx`, `frontend/app/components/AppShell.*`, `frontend/app/components/BenchmarksTable.*`, `frontend/app/components/ComparePanel.*`, global tokens, and new reference routes.
