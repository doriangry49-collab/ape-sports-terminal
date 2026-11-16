/**
 * Selectors:
 * Pure query functions for extracting specific slices of data from the view model.
 */

export function selectAllFixtures(state) {
  return state?.fixtures || [];
}

export function selectFixtureById(state, fixtureId) {
  if (!state || !state.fixtures) return null;
  return state.fixtures.find(f => f.fixtureId === fixtureId) || null;
}

export function selectAllEdges(state) {
  if (!state || !state.fixtures) return [];
  const all = [];
  for (const f of state.fixtures) {
    for (const e of f.edges || []) {
      all.push({
        ...e,
        fixtureId: f.fixtureId,
        homeTeam: f.homeTeam,
        awayTeam: f.awayTeam,
        competition: f.competition,
        league: e.league || f.league || f.competition || 'UNKNOWN',
        kickoff: f.kickoff,
        kickoff_trt: e.kickoff_trt || f.kickoff_trt || f.kickoffTrt,
        kickoffTrt: e.kickoffTrt || f.kickoffTrt || f.kickoff_trt,
      });
    }
  }
  return all;
}

export function selectTopEdges(state, limit = 5) {
  const edges = selectAllEdges(state);
  // Prioritize live monitored matches over static historical archive
  return edges
    .filter(e => typeof e.raw_edge === 'number')
    .sort((a, b) => {
      const aIsLive = a.kickoff_trt && a.kickoff_trt.includes('2026-11-');
      const bIsLive = b.kickoff_trt && b.kickoff_trt.includes('2026-11-');
      if (aIsLive && !bIsLive) return -1;
      if (!aIsLive && bIsLive) return 1;
      return b.raw_edge - a.raw_edge;
    })
    .slice(0, limit);
}

export function selectLongshots(state, minOdds = 5.0) {
  const edges = selectAllEdges(state);
  return edges
    .filter(e => typeof e.entry_odds === 'number' && e.entry_odds >= minOdds)
    .sort((a, b) => {
      const aIsLive = a.kickoff_trt && a.kickoff_trt.includes('2026-11-');
      const bIsLive = b.kickoff_trt && b.kickoff_trt.includes('2026-11-');
      if (aIsLive && !bIsLive) return -1;
      if (!aIsLive && bIsLive) return 1;
      return b.entry_odds - a.entry_odds;
    });
}

export function selectEdgesByMarket(state, marketName) {
  const edges = selectAllEdges(state);
  if (!marketName || marketName === 'ALL') return edges;
  return edges.filter(e => e.market.toUpperCase() === marketName.toUpperCase());
}
