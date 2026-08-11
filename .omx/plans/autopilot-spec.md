# EncodingDB public database redesign

Build a database-first Next.js frontend that preserves the query/analytics API. Replace the desktop workspace shell with a compact top navigation. Make the home page a browse page with the required headline, search/filter controls, corpus summary, an accessible virtualized raw-metrics table, contextual row comparison, and local My Hardware preferences. Add concise Hardware, Encoders, Methodology, and Run a benchmark pages; result rows retain an accessible provenance dialog until a dedicated backend result endpoint exists. Use neutral light/dark design tokens and responsive overflow rather than dashboard cards.

Acceptance criteria: no primary PL Score or workspace vocabulary; real API values only; URL-backed browse state; raw comparison metrics with compatibility warning; dark/light contrast; lint/typecheck/tests/build pass.
