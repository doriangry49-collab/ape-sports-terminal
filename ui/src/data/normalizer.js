/**
 * Normalizer & View-Model Adapter:
 * Maps raw snapshot fields to consistent UI presentation strings.
 * 
 * STRICT PROHIBITIONS:
 * - NO mathematical calculations (No no-vig, no edge formula, no normalization).
 * - Only formatting for display (e.g. 0.0411 -> "+4.11%", null -> "UNKNOWN").
 */

export function formatPercent(value, decimals = 2) {
  if (value === null || value === undefined || value === 'UNKNOWN' || isNaN(value)) {
    return 'UNKNOWN';
  }
  const pct = (value * 100).toFixed(decimals);
  return `${pct}%`;
}

export function formatSignedEdge(edgeValue, decimals = 2) {
  if (edgeValue === null || edgeValue === undefined || edgeValue === 'UNKNOWN' || isNaN(edgeValue)) {
    return 'UNKNOWN';
  }
  const pct = (edgeValue * 100).toFixed(decimals);
  if (edgeValue > 0) {
    return `+${pct}%`;
  }
  return `${pct}%`;
}

export function formatOdds(odds) {
  if (!odds || odds === 'UNKNOWN' || isNaN(odds)) {
    return 'UNKNOWN';
  }
  return Number(odds).toFixed(2);
}

export function formatIsoDate(isoString) {
  if (!isoString) return 'UNKNOWN';
  try {
    const d = new Date(isoString);
    return d.toUTCString().replace('GMT', 'UTC');
  } catch {
    return isoString;
  }
}

export function formatEvRoi(roiValue) {
  if (roiValue === null || roiValue === undefined || isNaN(roiValue)) {
    return '—';
  }
  const num = Number(roiValue);
  const prefix = num > 0 ? '+' : '';
  return `${prefix}${num.toFixed(1)}%`;
}

export function formatKellyStake(kellyPct, bankroll = 10000) {
  if (kellyPct === null || kellyPct === undefined || isNaN(kellyPct) || kellyPct <= 0) {
    return '0.0%';
  }
  const pct = Number(kellyPct);
  const stakeTl = Math.round((pct / 100) * bankroll);
  return `%${pct.toFixed(1)} (~${stakeTl} TL)`;
}

export function formatVig(vigValue) {
  if (vigValue === null || vigValue === undefined || isNaN(vigValue)) {
    return '—';
  }
  return `%${Number(vigValue).toFixed(1)}`;
}

export function normalizeSnapshot(rawSnapshot) {
  if (!rawSnapshot) return null;

  return {
    engineName: rawSnapshot.engine_name || 'Sports Intelligence Terminal',
    engineVersion: rawSnapshot.engine_version || 'v2.0-quant-shin',
    snapshotTimestamp: rawSnapshot.snapshot_timestamp || 'UNKNOWN',
    dataCutoff: rawSnapshot.data_cutoff || 'UNKNOWN',
    provider: rawSnapshot.provider || 'UNKNOWN',
    matchPhase: rawSnapshot.match_phase || 'PREMATCH',
    daemonStatus: rawSnapshot.daemon_status || {
      status: 'HEALTHY',
      leagues_scanned: 0,
      positive_ev_signals: 0,
      total_seen_alerts: 0
    },
    syndicatePro: rawSnapshot.syndicate_pro || {
      tiers: [],
      in_play_sniper_alerts: [],
      copula_sgp_combinations: [],
      clv_alpha_summary: {}
    },
    providerStatus: rawSnapshot.provider_status || [],
    totalFixtures: rawSnapshot.total_fixtures || 0,
    totalEdges: rawSnapshot.total_edges_calculated || 0,
    fixtures: (rawSnapshot.fixtures || []).map(f => ({
      fixtureId: f.fixture_id,
      homeTeam: f.home_team,
      awayTeam: f.away_team,
      competition: f.competition,
      league: f.league || f.competition || 'UNKNOWN',
      country: f.country,
      kickoff: f.kickoff,
      kickoffTrt: f.kickoff_trt || 'TBD',
      matchPhase: f.match_phase,
      sport: f.sport,
      modelVersion: f.model_version,
      dataCutoff: f.data_cutoff,
      snapshotId: f.snapshot_id,
      model1x2: f.model_1x2,
      totals25Model: f.totals_2_5_model,
      btts: f.btts,
      bookmakers: f.bookmakers,
      edges: (f.edges || []).map(e => ({
        ...e,
        league: e.league || f.league || f.competition || 'UNKNOWN',
        competition: e.competition || f.competition || f.league || 'UNKNOWN',
        shinMargin: typeof e.shin_margin === 'number' ? e.shin_margin : null,
        evRoi: typeof e.ev_roi === 'number' ? e.ev_roi : (typeof e.raw_edge === 'number' ? Number((e.raw_edge * 100).toFixed(1)) : null),
        halfKelly: typeof e.half_kelly === 'number' ? e.half_kelly : 0.0,
        fairOddsShin: e.fair_odds_shin || e.market_fair_odds || null,
        kickoffTrt: e.kickoff_trt || f.kickoff_trt || 'TBD'
      })),
      modelDerivedMarkets: f.model_derived_markets || {},
      modelUncertainty: f.model_uncertainty || 'UNKNOWN',
      clvStatus: f.clv_status || 'NOT_AVAILABLE'
    }))
  };
}
