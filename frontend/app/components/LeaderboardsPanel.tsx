import type { LeaderboardAnalyticsResponse, LeaderboardDecisionRow, PlFitMode } from "../lib/types";
import type { AnalyticsSearchState } from "../lib/queryState";
import styles from "./LeaderboardsPanel.module.css";

const MODE_ORDER: PlFitMode[] = ["balanced", "quality", "storage", "realtime", "custom"];

function formatScore(value: number | null): string {
  return value == null ? "Unavailable" : value.toFixed(2);
}

function formatBitrate(value: number | null): string {
  if (value == null) return "Unavailable";
  return `${(value / 1_000_000).toFixed(2)} Mbps`;
}

function modeSummary(row: LeaderboardDecisionRow, mode: PlFitMode): string {
  const fit = row.fit.modes[mode];
  if (fit.score == null) return fit.reasons[0] ?? "Unavailable";
  return `${fit.score.toFixed(2)} fit`;
}

export default function LeaderboardsPanel({
  payload,
  modeLinks,
  searchState,
}: {
  payload: LeaderboardAnalyticsResponse;
  modeLinks?: Partial<Record<PlFitMode, string>>;
  searchState?: AnalyticsSearchState;
}) {
  const { selectedMode, profiles, recommendation, rows } = payload;

  return <div className={styles.panel}>
    <header className={styles.header}>
      <div>
        <p className={styles.kicker}>Recommendation layer</p>
        <h1>Leaderboards</h1>
        <p className={styles.copy}>Find the best fit for one workload and environment. PL Fit reflects your priorities; PL Score remains fixed.</p>
      </div>
      <aside className={styles.banner}>
        <strong>Recommendation</strong>
        <span>{recommendation.label ?? "Withheld"}</span>
        <small>{recommendation.reason ?? "No additional note."}</small>
      </aside>
    </header>

    <nav className={styles.modes} aria-label="PL Fit modes">
      {MODE_ORDER.map((mode) => {
        const active = mode === selectedMode;
        const profile = profiles[mode];
        const href = modeLinks?.[mode];
        const label = profile.label;
        return href
          ? <a key={mode} href={href} aria-current={active ? "page" : undefined} className={active ? styles.modeActive : styles.modeLink}>{label}</a>
          : <span key={mode} aria-current={active ? "page" : undefined} className={active ? styles.modeActive : styles.modeLink}>{label}</span>;
      })}
    </nav>

    <form className={styles.controls} action="/leaderboards" method="get">
      <input type="hidden" name="fitMode" value={selectedMode} />
      <label>Exact environment
        <select name="environmentId" defaultValue={payload.environmentScope.selectedEnvironmentId ?? ""} required>
          <option value="">Select an environment</option>
          {payload.environmentScope.available.map((environment) => <option key={environment.environmentId} value={environment.environmentId}>{environment.label}</option>)}
        </select>
      </label>
      <label>Score context
        <select name="scoreContextId" defaultValue={payload.contextScope.selectedScoreContextId ?? ""} required>
          <option value="">Select a score context</option>
          {payload.contextScope.available.map((context) => <option key={context.scoreContextId} value={context.scoreContextId}>{context.label}</option>)}
        </select>
      </label>
      <label>Workload ID<input name="workloadId" placeholder="sports-action-960x540-24p" defaultValue={searchState?.workloadId ?? ""} /></label>
      <label>Resolution<input name="resolution" defaultValue={searchState?.resolution ?? "1080p"} /></label>
      <details className={styles.constraints}><summary>Quality, speed &amp; format limits</summary><div className={styles.constraintFields}><label>Minimum quality<input name="minimumQuality" type="number" step="0.1" defaultValue={searchState?.minimumQuality ?? ""} /></label>
      <label>Minimum realtime<input name="minimumRealtimeRatio" type="number" step="0.1" defaultValue={searchState?.minimumRealtimeRatio ?? ""} /></label>
      <label>Maximum Mbps<input name="maximumBitrateMbps" type="number" step="0.1" defaultValue={searchState?.maximumBitrateMbps ?? ""} /></label>
      <label>Compatible codecs<input name="compatibleCodecFamilies" placeholder="h264,hevc,av1" defaultValue={searchState?.compatibleCodecFamilies ?? ""} /></label>
      </div></details><label className={styles.checkbox}><input name="requireRecommendationEligibility" type="checkbox" value="1" defaultChecked={searchState?.requireRecommendationEligibility} /> Require recommendation-grade evidence</label>
      <button className="btn btn-primary" type="submit">Apply exact scope</button>
    </form>

    {!payload.environmentScope.exact ? <p className={styles.withheld}>Ranking and Pareto analysis are withheld until one immutable Environment is selected. Results from different machines are never compared.</p> : null}
    {payload.environmentScope.exact && !payload.contextScope.exact ? <p className={styles.withheld}>Ranking is withheld until one immutable ScoreContext is selected. Historical score contexts are never mixed.</p> : null}

    <div className={styles.modeCard}>
      <strong>{profiles[selectedMode].label}</strong>
      <span>Weights Q/B/S: {profiles[selectedMode].weights.quality.toFixed(2)} / {profiles[selectedMode].weights.bitrate.toFixed(2)} / {profiles[selectedMode].weights.speed.toFixed(2)}</span>
      <small>Hard constraints are applied before ranking. Recommendation eligibility remains separate from desirability.</small>
    </div>

    <div className={styles.tableWrap} role="region" aria-label="Leaderboard results" tabIndex={0}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Rank</th>
            <th>Encoder</th>
            <th>PL Score</th>
            <th>PL Fit</th>
            <th>Bitrate</th>
            <th>Realtime</th>
            <th>Evidence</th>
            <th>Pareto</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={9} className={styles.empty}>No results match this scope. Adjust your filters to explore available measurements.</td></tr>}
          {rows.map((row) => {
            const fit = row.fit.modes[selectedMode];
            return <tr key={row.rowId} className={!row.pareto.efficient ? styles.dominated : undefined}>
              <td>{fit.rank}</td>
              <td>
                <strong>{row.encoderName}</strong>
                <div>{row.preset}</div>
                <div>{row.rateControl.label}</div>
                {row.fit.recommended ? <span className={styles.badge}>Recommended</span> : null}
              </td>
              <td>{formatScore(row.plScore)}</td>
              <td>
                <strong>{modeSummary(row, selectedMode)}</strong>
                {!fit.eligible && fit.reasons.length > 0 ? <div>{fit.reasons[0]}</div> : null}
              </td>
              <td>{formatBitrate(row.avgVideoBitrateBps)}</td>
              <td>{row.realtimeRatio == null ? "Unavailable" : `${row.realtimeRatio.toFixed(2)}x`}</td>
              <td>
                <strong>{row.evidence.evidenceTier}</strong>
                <div>{row.evidence.eligibleForDefaultRecommendation ? "Recommendation-eligible" : "Provisional"}</div>
              </td>
              <td>{row.pareto.available ? (row.pareto.efficient ? "Efficient" : "Dominated") : row.pareto.unavailableReason}</td>
              <td><details className={styles.rowDetails}><summary>Scope &amp; metrics</summary><dl>
                <dt>Environment</dt><dd>{row.hardwareLabel}</dd>
                <dt>Workload</dt><dd>{row.workloadId}</dd>
                <dt>Canonical Q/B/S</dt><dd>{formatScore(row.plScoreComponents?.quality ?? null)} / {formatScore(row.plScoreComponents?.bitrate ?? null)} / {formatScore(row.plScoreComponents?.speed ?? null)}</dd>
                <dt>BD-rate</dt><dd>{row.bdRate.available ? `${row.bdRate.valuePercent!.toFixed(2)}% vs ${row.bdRate.versusLabel}` : row.bdRate.unavailableReason}</dd>
                <dt>Reference / formula</dt><dd>{row.context.referenceContextVersion ?? "No reference context"} / {row.context.formulaVersion ?? "unknown"}</dd>
                <dt>Protocol / suite</dt><dd>{row.context.benchmarkProtocolVersion ?? "No protocol"} / {row.context.sourceSuiteVersion ?? "No suite"}</dd>
                <dt>Quality model / context</dt><dd>{row.context.qualityModelId ?? "No model"} / {row.context.scoreContextId}</dd>
              </dl></details></td>
            </tr>;
          })}
        </tbody>
      </table>
    </div>
  </div>;
}
