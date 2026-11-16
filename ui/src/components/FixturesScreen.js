/**
 * Screen 2: Football Fixtures
 * Explorer for all active matches with real snapshot data
 */

import { formatOdds, formatPercent, formatSignedEdge } from '../data/normalizer.js';

function extractCardOdds(f) {
  const bks = f.bookmakers || {};
  if (bks.NESINE?.['1X2']?.odds) {
    const o = bks.NESINE['1X2'].odds;
    const tot = bks.NESINE['TOTALS_2.5']?.odds;
    return {
      bookName: 'NESINE',
      homeOdd: o['1'] || (f.homeTeam && o[f.homeTeam]) || 'N/A',
      drawOdd: o['X'] || o['Draw'] || 'N/A',
      awayOdd: o['2'] || (f.awayTeam && o[f.awayTeam]) || 'N/A',
      overOdd: tot?.['Over 2.5'] || 'N/A',
      underOdd: tot?.['Under 2.5'] || 'N/A',
    };
  }
  if (bks.Bovada?.['1X2']?.odds) {
    const o = bks.Bovada['1X2'].odds;
    const tot = bks.Bovada['TOTALS_2.5']?.odds;
    return {
      bookName: 'Bovada',
      homeOdd: (f.homeTeam && o[f.homeTeam]) || o['1'] || 'N/A',
      drawOdd: o['Draw'] || o['X'] || 'N/A',
      awayOdd: (f.awayTeam && o[f.awayTeam]) || o['2'] || 'N/A',
      overOdd: tot?.['Over 2.5'] || 'N/A',
      underOdd: tot?.['Under 2.5'] || 'N/A',
    };
  }
  if (bks.PINNACLE?.['1X2']?.odds) {
    const o = bks.PINNACLE['1X2'].odds;
    return {
      bookName: 'Pinnacle',
      homeOdd: o['1'] || 'N/A',
      drawOdd: o['X'] || 'N/A',
      awayOdd: o['2'] || 'N/A',
      overOdd: 'N/A',
      underOdd: 'N/A',
    };
  }
  return { bookName: 'Market', homeOdd: 'N/A', drawOdd: 'N/A', awayOdd: 'N/A', overOdd: 'N/A', underOdd: 'N/A' };
}

export function renderFixtures(state, onSelectFixture) {
  const allFixtures = state.fixtures || [];
  const filters = state.fixtureFilters || { country: 'ALL', competition: 'ALL', phase: 'ALL' };

  const countries = Array.from(new Set(allFixtures.map(f => f.country).filter(Boolean))).sort();
  const competitions = Array.from(new Set(allFixtures.map(f => f.competition).filter(Boolean))).sort();

  const fixtures = allFixtures.filter(f => {
    if (filters.country && filters.country !== 'ALL' && f.country !== filters.country) return false;
    if (filters.competition && filters.competition !== 'ALL' && f.competition !== filters.competition) return false;
    if (filters.phase && filters.phase !== 'ALL') {
      if (filters.phase === 'PREMATCH' && f.matchPhase !== 'PREMATCH') return false;
      if (filters.phase === 'LIVE_AND_PREMATCH' && !['LIVE', 'PREMATCH'].includes(f.matchPhase)) return false;
    }
    return true;
  });

  return `
    <div class="fixtures-view">
      <div class="filter-bar">
        <div class="filter-group">
          <span class="filter-label">Sport:</span>
          <select class="filter-select" id="filter-sport">
            <option value="Football" selected>Football (Soccer)</option>
            <option value="NBA">Basketball (NBA)</option>
          </select>
        </div>
        <div class="filter-group">
          <span class="filter-label">Country:</span>
          <select class="filter-select" id="filter-country">
            <option value="ALL" ${filters.country === 'ALL' ? 'selected' : ''}>All Countries (${countries.length})</option>
            ${countries.map(c => `<option value="${c}" ${filters.country === c ? 'selected' : ''}>${c}</option>`).join('')}
          </select>
        </div>
        <div class="filter-group">
          <span class="filter-label">Competition:</span>
          <select class="filter-select" id="filter-competition">
            <option value="ALL" ${filters.competition === 'ALL' ? 'selected' : ''}>All Competitions (${competitions.length})</option>
            ${competitions.map(c => `<option value="${c}" ${filters.competition === c ? 'selected' : ''}>${c}</option>`).join('')}
          </select>
        </div>
        <div class="filter-group">
          <span class="filter-label">Phase:</span>
          <select class="filter-select" id="filter-phase">
            <option value="ALL" ${filters.phase === 'ALL' ? 'selected' : ''}>All Phases (${allFixtures.length})</option>
            <option value="LIVE_AND_PREMATCH" ${filters.phase === 'LIVE_AND_PREMATCH' ? 'selected' : ''}>Live & Upcoming</option>
            <option value="PREMATCH" ${filters.phase === 'PREMATCH' ? 'selected' : ''}>Pre-match Archive</option>
          </select>
        </div>
      </div>

      <div class="grid-3">
        ${fixtures.map(f => {
          const cardOdds = extractCardOdds(f);
          const edges = f.edges || [];
          const edgeHome = edges.find(e => e.market === '1X2' && e.selection === 'HOME');
          const edgeOver = edges.find(e => e.market === 'TOTALS' && e.selection === 'OVER_2.5');

          return `
            <div class="panel" style="display: flex; flex-direction: column; justify-content: space-between;">
              <div>
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.75rem;">
                  <div>
                    <span class="badge badge-slate" style="font-size: 0.7rem;">${f.competition}</span>
                    <span class="badge badge-emerald" style="font-size: 0.7rem; margin-left: 0.3rem;">${f.matchPhase}</span>
                  </div>
                  <span class="mono-num" style="font-size: 0.75rem; color: var(--text-muted);">
                    ${f.kickoff ? f.kickoff.substring(5, 16).replace('T', ' ') : 'N/A'} UTC
                  </span>
                </div>

                <div style="margin: 0.8rem 0 1.2rem 0;">
                  <h3 style="font-size: 1.15rem; font-weight: 700; color: var(--text-bright); line-height: 1.3;">
                    ${f.homeTeam}
                  </h3>
                  <div style="font-size: 0.78rem; color: var(--text-muted); margin: 0.1rem 0;">vs</div>
                  <h3 style="font-size: 1.15rem; font-weight: 700; color: var(--text-bright); line-height: 1.3;">
                    ${f.awayTeam}
                  </h3>
                </div>

                <!-- 1X2 Comparison Box -->
                <div style="background: rgba(0,0,0,0.3); padding: 0.75rem; border-radius: var(--radius-sm); margin-bottom: 0.6rem; border: 1px solid var(--border-subtle);">
                  <div style="display: flex; justify-content: space-between; font-size: 0.75rem; font-family: var(--font-mono); color: var(--text-muted); margin-bottom: 0.3rem;">
                    <span>1X2 (${cardOdds.bookName})</span>
                    <span>Model Prob</span>
                    <span>Edge</span>
                  </div>
                  <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.82rem; margin-bottom: 0.2rem;">
                    <span>1: <strong class="mono-num">${cardOdds.homeOdd}</strong></span>
                    <span class="mono-num">${formatPercent(f.model1x2?.HOME)}</span>
                    <span class="badge ${edgeHome && edgeHome.raw_edge > 0 ? 'badge-emerald' : 'badge-rose'}" style="font-size: 0.72rem;">
                      ${edgeHome ? formatSignedEdge(edgeHome.raw_edge) : 'N/A'}
                    </span>
                  </div>
                </div>

                <!-- Over/Under 2.5 Box -->
                <div style="background: rgba(0,0,0,0.3); padding: 0.75rem; border-radius: var(--radius-sm); margin-bottom: 0.6rem; border: 1px solid var(--border-subtle);">
                  <div style="display: flex; justify-content: space-between; font-size: 0.75rem; font-family: var(--font-mono); color: var(--text-muted); margin-bottom: 0.3rem;">
                    <span>Totals 2.5 (${cardOdds.bookName})</span>
                    <span>Model Over</span>
                    <span>Edge</span>
                  </div>
                  <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.82rem;">
                    <span>Over: <strong class="mono-num">${cardOdds.overOdd}</strong></span>
                    <span class="mono-num">${formatPercent(f.totals25Model?.OVER)}</span>
                    <span class="badge ${edgeOver && edgeOver.raw_edge > 0 ? 'badge-emerald' : 'badge-rose'}" style="font-size: 0.72rem;">
                      ${edgeOver ? formatSignedEdge(edgeOver.raw_edge) : 'N/A'}
                    </span>
                  </div>
                </div>

                <!-- BTTS Transparency Box -->
                <div style="background: rgba(0,0,0,0.2); padding: 0.5rem 0.75rem; border-radius: var(--radius-sm); margin-bottom: 1rem; border: 1px dashed var(--border-subtle); display: flex; justify-content: space-between; align-items: center;">
                  <span style="font-size: 0.75rem; font-family: var(--font-mono); color: var(--text-muted);">Country / Tier:</span>
                  <span class="badge badge-slate" style="font-size: 0.7rem;">${f.country || 'Global'}</span>
                </div>
              </div>

              <button class="btn btn-outline" style="width: 100%; justify-content: center; margin-top: 0.5rem;" data-fixture="${f.fixtureId}">
                Inspect Full Match Engine →
              </button>
            </div>
          `;
        }).join('')}
      </div>
    </div>
  `;
}
