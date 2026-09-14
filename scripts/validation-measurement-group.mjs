// Build the server receipt from completed local measurements, never a claimed threshold.
export function validationMeasurementGroup(result) {
  const counted = result.runs.filter(run => run.countedForStability === true);
  const measured = result.runs.filter(run => run.schedule.phase === 'measured');
  if (counted.length < 2 || counted.length > 4 || counted.length !== result.measuredRunsCounted
    || !Number.isInteger(result.measuredRunsRequired) || result.measuredRunsRequired < 2
    || !Number.isInteger(result.measuredRunsCompleted) || result.measuredRunsCompleted !== measured.length
    || result.measuredRunsCompleted < result.measuredRunsRequired) throw new Error('Incomplete validation measurement group');
  const first = counted[0].schedule;
  const seen = new Set();
  const countedAttempts = counted.map(run => {
    const index = run.schedule.repetition_index;
    const elapsed = run.timing?.elapsed_s;
    if (run.schedule.phase !== 'measured' || run.overallValidity?.state !== 'valid'
      || run.schedule.campaign_id !== first.campaign_id || run.schedule.recipe_id !== first.recipe_id
      || !Number.isInteger(index) || index < 0 || seen.has(index)
      || !Number.isFinite(elapsed) || elapsed <= 0) throw new Error('Invalid counted validation attempt');
    seen.add(index);
    return { repetitionIndex: index, encodeWallTimeMs: elapsed * 1000 };
  }).sort((a, b) => a.repetitionIndex - b.repetitionIndex);
  return {
    schemaVersion: 'encodingdb-measurement-group/v1', campaignId: first.campaign_id,
    repetitionGroupId: `${first.campaign_id}:${first.recipe_id}`, completed: true, countedAttempts,
  };
}
