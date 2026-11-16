/**
 * Screen 3: Match Detail
 * Deep Dive Inspection: Model vs Market Discrepancy & Odds Decomposition
 */

import { selectFixtureById } from '../data/selectors.js';
import { formatOdds, formatPercent, formatSignedEdge } from '../data/normalizer.js';

export function renderMatchDetail(state, selectedFixtureId) {
  // Select fixture by id or fall back to first fixture
  const fixture = (selectedFixtureId ? selectFixtureById(state, selectedFixtureId) : null) || state.fixtures?.[0];

  if (!fixture) {
    return `<div class="empty-state"><p>No fixture data found in snapshot.</p></div>`;
  }

  const bks = fixture.bookmakers || {};
  let primaryBook = 'NESINE';
  if (!bks.NESINE && bks.Bovada) primaryBook = 'Bovada';
  else if (!bks.NESINE && !bks.Bovada && bks.PINNACLE) primaryBook = 'PINNACLE';
  else if (!bks.NESINE && !bks.Bovada && !bks.PINNACLE) primaryBook = Object.keys(bks)[0] || 'Market';

  const book1x2 = bks[primaryBook]?.['1X2'] || {};
  const bookTot = bks[primaryBook]?.['TOTALS_2.5'] || {};
  const odds1x2 = book1x2.odds || {};
  const noVig1x2 = book1x2.no_vig || {};
  const rawImplied1x2 = book1x2.raw_implied || {};
  const overround1x2 = book1x2.overround || 1.05;

  const homeOdds = odds1x2['1'] || (fixture.homeTeam && odds1x2[fixture.homeTeam]) || 'N/A';
  const drawOdds = odds1x2['X'] || odds1x2['Draw'] || 'N/A';
  const awayOdds = odds1x2['2'] || (fixture.awayTeam && odds1x2[fixture.awayTeam]) || 'N/A';

  const homeNoVig = noVig1x2['1'] || (fixture.homeTeam && noVig1x2[fixture.homeTeam]) || (homeOdds !== 'N/A' ? (1.0 / parseFloat(homeOdds)) / overround1x2 : 0.0);
  const drawNoVig = noVig1x2['X'] || noVig1x2['Draw'] || (drawOdds !== 'N/A' ? (1.0 / parseFloat(drawOdds)) / overround1x2 : 0.0);
  const awayNoVig = noVig1x2['2'] || (fixture.awayTeam && noVig1x2[fixture.awayTeam]) || (awayOdds !== 'N/A' ? (1.0 / parseFloat(awayOdds)) / overround1x2 : 0.0);

  const homeImplied = rawImplied1x2['1'] || (fixture.homeTeam && rawImplied1x2[fixture.homeTeam]) || (homeOdds !== 'N/A' ? 1.0 / parseFloat(homeOdds) : 0.0);
  const drawImplied = rawImplied1x2['X'] || rawImplied1x2['Draw'] || (drawOdds !== 'N/A' ? 1.0 / parseFloat(drawOdds) : 0.0);
  const awayImplied = rawImplied1x2['2'] || (fixture.awayTeam && rawImplied1x2[fixture.awayTeam]) || (awayOdds !== 'N/A' ? 1.0 / parseFloat(awayOdds) : 0.0);

  const edges = fixture.edges || [];
  const edgeHome = edges.find(e => e.market === '1X2' && e.selection === 'HOME');
  const edgeDraw = edges.find(e => e.market === '1X2' && e.selection === 'DRAW');
  const edgeAway = edges.find(e => e.market === '1X2' && e.selection === 'AWAY');

  const oddsTot = bookTot.odds || {};
  const noVigTot = bookTot.no_vig || {};
  const rawImpliedTot = bookTot.raw_implied || {};
  const overroundTot = bookTot.overround || 1.06;

  const overOdds = oddsTot['Over 2.5'] || 'N/A';
  const underOdds = oddsTot['Under 2.5'] || 'N/A';
  const overNoVig = noVigTot['Over 2.5'] || (overOdds !== 'N/A' ? (1.0 / parseFloat(overOdds)) / overroundTot : 0.0);
  const underNoVig = noVigTot['Under 2.5'] || (underOdds !== 'N/A' ? (1.0 / parseFloat(underOdds)) / overroundTot : 0.0);
  const overImplied = rawImpliedTot['Over 2.5'] || (overOdds !== 'N/A' ? 1.0 / parseFloat(overOdds) : 0.0);
  const underImplied = rawImpliedTot['Under 2.5'] || (underOdds !== 'N/A' ? 1.0 / parseFloat(underOdds) : 0.0);

  const edgeOver = edges.find(e => e.market === 'TOTALS' && e.selection === 'OVER_2.5');
  const edgeUnder = edges.find(e => e.market === 'TOTALS' && e.selection === 'UNDER_2.5');

  return `
    <div class="match-detail-view">
      <!-- Fixture Header Panel -->
      <div class="panel" style="margin-bottom: 1.5rem; background: linear-gradient(135deg, rgba(14,19,31,0.9), rgba(24,34,54,0.7));">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 1rem;">
          <div>
            <div style="display: flex; gap: 0.5rem; margin-bottom: 0.5rem;">
              <span class="badge badge-cyan">${fixture.competition}</span>
              <span class="badge badge-emerald">${fixture.matchPhase}</span>
              <span class="badge badge-slate">PROVIDER: ${primaryBook}</span>
              <span class="badge badge-slate">${fixture.country || 'Global'}</span>
            </div>
            <h1 style="font-size: 1.85rem; font-weight: 800; color: var(--text-bright); letter-spacing: -0.5px;">
              ${fixture.homeTeam} <span style="color: var(--text-muted); font-weight: 300;">vs</span> ${fixture.awayTeam}
            </h1>
            <div style="font-family: var(--font-mono); font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.3rem;">
              Kickoff: ${fixture.kickoff ? fixture.kickoff.replace('T', ' ') : 'N/A'} | Model: ${fixture.modelVersion}
            </div>
          </div>

          <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 0.4rem;">
            <div class="badge badge-slate" style="font-size: 0.72rem;">SNAPSHOT: ${fixture.snapshotId}</div>
            <div class="badge badge-slate" style="font-size: 0.72rem;">DATA CUTOFF: ${fixture.dataCutoff?.substring(0, 19).replace('T', ' ')} UTC</div>
            <div class="badge badge-amber" style="font-size: 0.72rem;">UNCERTAINTY: ${fixture.modelUncertainty}</div>
            <div class="badge badge-slate" style="font-size: 0.72rem;">CLV STATUS: ${fixture.clvStatus}</div>
          </div>
        </div>
      </div>

      <!-- Probability Comparison Overview (Model vs Market Consensus) -->
      <div class="panel" style="margin-bottom: 1.5rem;">
        <div class="panel-header">
          <span class="panel-title">📊 Model Probability vs Market No-Vig Fair Consensus (${primaryBook})</span>
          <span class="badge badge-cyan">SHIN ALGORITHM ARBITRATION</span>
        </div>

        <div class="grid-3" style="margin-top: 1rem;">
          <!-- Home Prob -->
          <div style="background: rgba(0,0,0,0.3); padding: 1rem; border-radius: var(--radius-md); border: 1px solid var(--border-subtle);">
            <div style="display: flex; justify-content: space-between; font-weight: 600; margin-bottom: 0.5rem;">
              <span>${fixture.homeTeam} (Home)</span>
              <span class="badge ${edgeHome && edgeHome.raw_edge > 0 ? 'badge-emerald' : 'badge-rose'}">
                ${edgeHome ? formatSignedEdge(edgeHome.raw_edge) : 'N/A'}
              </span>
            </div>
            <div class="prob-compare-bar">
              <div class="bar-row">
                <span class="bar-label">MODEL</span>
                <div class="bar-track"><div class="bar-fill model" style="width: ${(fixture.model1x2?.HOME * 100) || 0}%;"></div></div>
                <span class="bar-val" style="color: var(--accent-cyan);">${formatPercent(fixture.model1x2?.HOME)}</span>
              </div>
              <div class="bar-row">
                <span class="bar-label">MARKET</span>
                <div class="bar-track"><div class="bar-fill market" style="width: ${(homeNoVig * 100) || 0}%;"></div></div>
                <span class="bar-val" style="color: var(--accent-violet);">${formatPercent(homeNoVig)}</span>
              </div>
            </div>
          </div>

          <!-- Draw Prob -->
          <div style="background: rgba(0,0,0,0.3); padding: 1rem; border-radius: var(--radius-md); border: 1px solid var(--border-subtle);">
            <div style="display: flex; justify-content: space-between; font-weight: 600; margin-bottom: 0.5rem;">
              <span>Draw (X)</span>
              <span class="badge ${edgeDraw && edgeDraw.raw_edge > 0 ? 'badge-emerald' : 'badge-rose'}">
                ${edgeDraw ? formatSignedEdge(edgeDraw.raw_edge) : 'N/A'}
              </span>
            </div>
            <div class="prob-compare-bar">
              <div class="bar-row">
                <span class="bar-label">MODEL</span>
                <div class="bar-track"><div class="bar-fill model" style="width: ${(fixture.model1x2?.DRAW * 100) || 0}%;"></div></div>
                <span class="bar-val" style="color: var(--accent-cyan);">${formatPercent(fixture.model1x2?.DRAW)}</span>
              </div>
              <div class="bar-row">
                <span class="bar-label">MARKET</span>
                <div class="bar-track"><div class="bar-fill market" style="width: ${(drawNoVig * 100) || 0}%;"></div></div>
                <span class="bar-val" style="color: var(--accent-violet);">${formatPercent(drawNoVig)}</span>
              </div>
            </div>
          </div>

          <!-- Away Prob -->
          <div style="background: rgba(0,0,0,0.3); padding: 1rem; border-radius: var(--radius-md); border: 1px solid var(--border-subtle);">
            <div style="display: flex; justify-content: space-between; font-weight: 600; margin-bottom: 0.5rem;">
              <span>${fixture.awayTeam} (Away)</span>
              <span class="badge ${edgeAway && edgeAway.raw_edge > 0 ? 'badge-emerald' : 'badge-rose'}">
                ${edgeAway ? formatSignedEdge(edgeAway.raw_edge) : 'N/A'}
              </span>
            </div>
            <div class="prob-compare-bar">
              <div class="bar-row">
                <span class="bar-label">MODEL</span>
                <div class="bar-track"><div class="bar-fill model" style="width: ${(fixture.model1x2?.AWAY * 100) || 0}%;"></div></div>
                <span class="bar-val" style="color: var(--accent-cyan);">${formatPercent(fixture.model1x2?.AWAY)}</span>
              </div>
              <div class="bar-row">
                <span class="bar-label">MARKET</span>
                <div class="bar-track"><div class="bar-fill market" style="width: ${(awayNoVig * 100) || 0}%;"></div></div>
                <span class="bar-val" style="color: var(--accent-violet);">${formatPercent(awayNoVig)}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 1X2 Market Decomposition Table -->
      <div class="panel" style="margin-bottom: 1.5rem;">
        <div class="panel-header">
          <span class="panel-title">⚽ Market 1: 1X2 (Match Winner) — ${primaryBook} Margin & Raw Edge</span>
          <span class="badge badge-emerald">BOOKMAKER OFFERED</span>
        </div>
        <table class="terminal-table">
          <thead>
            <tr>
              <th>Selection</th>
              <th>Bookmaker</th>
              <th>Entry Odds</th>
              <th>Raw Implied</th>
              <th>Overround</th>
              <th>Shin No-Vig</th>
              <th>Model Prob</th>
              <th>Model Fair Odds</th>
              <th>Raw Edge</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>${fixture.homeTeam}</strong> (Home)</td>
              <td>${primaryBook}</td>
              <td class="mono-num"><strong>${homeOdds}</strong></td>
              <td class="mono-num">${formatPercent(homeImplied)}</td>
              <td class="mono-num">${formatPercent(overround1x2 - 1.0)} (${formatOdds(overround1x2)})</td>
              <td class="mono-num" style="color: var(--accent-violet); font-weight: 600;">${formatPercent(homeNoVig)}</td>
              <td class="mono-num" style="color: var(--accent-cyan); font-weight: 600;">${formatPercent(fixture.model1x2?.HOME)}</td>
              <td class="mono-num">${formatOdds(fixture.model1x2?.fair_home_odds)}</td>
              <td><span class="badge ${edgeHome && edgeHome.raw_edge > 0 ? 'badge-emerald' : 'badge-rose'}">${edgeHome ? formatSignedEdge(edgeHome.raw_edge) : 'N/A'}</span></td>
            </tr>
            <tr>
              <td><strong>Draw</strong> (X)</td>
              <td>${primaryBook}</td>
              <td class="mono-num"><strong>${drawOdds}</strong></td>
              <td class="mono-num">${formatPercent(drawImplied)}</td>
              <td class="mono-num">${formatPercent(overround1x2 - 1.0)} (${formatOdds(overround1x2)})</td>
              <td class="mono-num" style="color: var(--accent-violet); font-weight: 600;">${formatPercent(drawNoVig)}</td>
              <td class="mono-num" style="color: var(--accent-cyan); font-weight: 600;">${formatPercent(fixture.model1x2?.DRAW)}</td>
              <td class="mono-num">${formatOdds(fixture.model1x2?.fair_draw_odds)}</td>
              <td><span class="badge ${edgeDraw && edgeDraw.raw_edge > 0 ? 'badge-emerald' : 'badge-rose'}">${edgeDraw ? formatSignedEdge(edgeDraw.raw_edge) : 'N/A'}</span></td>
            </tr>
            <tr>
              <td><strong>${fixture.awayTeam}</strong> (Away)</td>
              <td>${primaryBook}</td>
              <td class="mono-num"><strong>${awayOdds}</strong></td>
              <td class="mono-num">${formatPercent(awayImplied)}</td>
              <td class="mono-num">${formatPercent(overround1x2 - 1.0)} (${formatOdds(overround1x2)})</td>
              <td class="mono-num" style="color: var(--accent-violet); font-weight: 600;">${formatPercent(awayNoVig)}</td>
              <td class="mono-num" style="color: var(--accent-cyan); font-weight: 600;">${formatPercent(fixture.model1x2?.AWAY)}</td>
              <td class="mono-num">${formatOdds(fixture.model1x2?.fair_away_odds)}</td>
              <td><span class="badge ${edgeAway && edgeAway.raw_edge > 0 ? 'badge-emerald' : 'badge-rose'}">${edgeAway ? formatSignedEdge(edgeAway.raw_edge) : 'N/A'}</span></td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Totals 2.5 Market Decomposition Table -->
      <div class="panel" style="margin-bottom: 1.5rem;">
        <div class="panel-header">
          <span class="panel-title">🎯 Market 2: Totals (Over / Under 2.5 Goals) — ${primaryBook}</span>
          <span class="badge badge-emerald">BOOKMAKER OFFERED</span>
        </div>
        <table class="terminal-table">
          <thead>
            <tr>
              <th>Selection</th>
              <th>Bookmaker</th>
              <th>Entry Odds</th>
              <th>Raw Implied</th>
              <th>Overround</th>
              <th>No-Vig (Norm)</th>
              <th>Model Prob</th>
              <th>Model Fair Odds</th>
              <th>Raw Edge</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Over 2.5 Goals</strong></td>
              <td>${primaryBook}</td>
              <td class="mono-num"><strong>${overOdds}</strong></td>
              <td class="mono-num">${formatPercent(overImplied)}</td>
              <td class="mono-num">${formatPercent(overroundTot - 1.0)} (${formatOdds(overroundTot)})</td>
              <td class="mono-num" style="color: var(--accent-violet); font-weight: 600;">${formatPercent(overNoVig)}</td>
              <td class="mono-num" style="color: var(--accent-cyan); font-weight: 600;">${formatPercent(fixture.totals25Model?.OVER)}</td>
              <td class="mono-num">${formatOdds(1.0 / (fixture.totals25Model?.OVER || 0.5))}</td>
              <td><span class="badge ${edgeOver && edgeOver.raw_edge > 0 ? 'badge-emerald' : 'badge-rose'}">${edgeOver ? formatSignedEdge(edgeOver.raw_edge) : 'N/A'}</span></td>
            </tr>
            <tr>
              <td><strong>Under 2.5 Goals</strong></td>
              <td>${primaryBook}</td>
              <td class="mono-num"><strong>${underOdds}</strong></td>
              <td class="mono-num">${formatPercent(underImplied)}</td>
              <td class="mono-num">${formatPercent(overroundTot - 1.0)} (${formatOdds(overroundTot)})</td>
              <td class="mono-num" style="color: var(--accent-violet); font-weight: 600;">${formatPercent(underNoVig)}</td>
              <td class="mono-num" style="color: var(--accent-cyan); font-weight: 600;">${formatPercent(fixture.totals25Model?.UNDER)}</td>
              <td class="mono-num">${formatOdds(1.0 / (fixture.totals25Model?.UNDER || 0.5))}</td>
              <td><span class="badge ${edgeUnder && edgeUnder.raw_edge > 0 ? 'badge-emerald' : 'badge-rose'}">${edgeUnder ? formatSignedEdge(edgeUnder.raw_edge) : 'N/A'}</span></td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- BTTS Market Panel -->
      <div class="panel" style="margin-bottom: 1.5rem; border: 1px dashed rgba(245, 158, 11, 0.4);">
        <div class="panel-header">
          <span class="panel-title">⚡ Market 3: BTTS (Both Teams To Score)</span>
          <span class="badge badge-amber">${fixture.btts?.status || 'MODEL_ONLY'}</span>
        </div>
        <div style="background: rgba(0,0,0,0.25); padding: 1rem; border-radius: var(--radius-sm); margin-bottom: 1rem;">
          <div style="color: var(--accent-amber); font-weight: 600; font-size: 0.88rem; margin-bottom: 0.3rem;">
            ℹ️ Bülten & Model Şeffaflık Raporu
          </div>
          <div style="color: var(--text-secondary); font-size: 0.82rem; line-height: 1.4;">
            Poisson modelimiz her iki takımın gol atma olasılığını türetmiştir. Bookmaker bülteninde resmi oran bulunmadığında sahte oran üretilmez, alanlar dürüstçe <strong>DATA UNAVAILABLE</strong> olarak sunulur.
          </div>
        </div>

        <table class="terminal-table">
          <thead>
            <tr>
              <th>Selection</th>
              <th>Model Probability</th>
              <th>Bookmaker Odds</th>
              <th>Market No-Vig Prob</th>
              <th>Raw Edge</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Both Teams To Score: YES</strong></td>
              <td class="mono-num" style="color: var(--accent-cyan); font-weight: 600;">${formatPercent(fixture.btts?.model_probability?.YES || 0.5)}</td>
              <td><span class="badge badge-slate">${fixture.btts?.bookmaker_odds || 'DATA UNAVAILABLE'}</span></td>
              <td><span class="badge badge-slate">${fixture.btts?.market_no_vig_probability || 'UNKNOWN'}</span></td>
              <td><span class="badge badge-slate">${fixture.btts?.raw_edge || 'UNKNOWN'}</span></td>
            </tr>
            <tr>
              <td><strong>Both Teams To Score: NO</strong></td>
              <td class="mono-num" style="color: var(--accent-cyan); font-weight: 600;">${formatPercent(fixture.btts?.model_probability?.NO || 0.5)}</td>
              <td><span class="badge badge-slate">${fixture.btts?.bookmaker_odds || 'DATA UNAVAILABLE'}</span></td>
              <td><span class="badge badge-slate">${fixture.btts?.market_no_vig_probability || 'UNKNOWN'}</span></td>
              <td><span class="badge badge-slate">${fixture.btts?.raw_edge || 'UNKNOWN'}</span></td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Model Derived Markets -->
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">🔬 Model-Derived Markets (High Variance / Poisson Projections)</span>
          <span class="badge badge-slate">MODEL DERIVED</span>
        </div>
        <div style="font-size: 0.82rem; color: var(--text-secondary); margin-bottom: 1rem;">
          Aşağıdaki marketler Poisson bivariate modelimizden türetilmiştir. Bookmaker bülteninde henüz oran bulunmadığı için Phase 2A Edge motoruna dahil edilmemiştir.
        </div>

        <div class="grid-2">
          <!-- Top Correct Scores -->
          <div style="background: rgba(0,0,0,0.25); padding: 1rem; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <h4 style="font-size: 0.9rem; font-weight: 600; color: var(--text-bright); margin-bottom: 0.6rem;">Top Correct Scores (Probabilities)</h4>
            <div style="display: flex; flex-direction: column; gap: 0.4rem;">
              ${Object.entries(fixture.modelDerivedMarkets?.top_correct_scores || {}).slice(0, 5).map(([score, prob]) => `
                <div style="display: flex; justify-content: space-between; font-size: 0.82rem; font-family: var(--font-mono);">
                  <span>Skor ${score}:</span>
                  <span style="color: var(--accent-cyan); font-weight: 600;">${formatPercent(prob)}</span>
                  <span class="badge badge-slate" style="font-size: 0.68rem;">ODDS UNAVAILABLE</span>
                </div>
              `).join('')}
              ${(!fixture.modelDerivedMarkets?.top_correct_scores || Object.keys(fixture.modelDerivedMarkets.top_correct_scores).length === 0) ? `
                <div style="color: var(--text-muted); font-size: 0.8rem;">Skor modeli canlı bültende henüz simüle edilmedi.</div>
              ` : ''}
            </div>
          </div>

          <!-- HT / FT Projections -->
          <div style="background: rgba(0,0,0,0.25); padding: 1rem; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <h4 style="font-size: 0.9rem; font-weight: 600; color: var(--text-bright); margin-bottom: 0.6rem;">HT / FT Projections (Probabilities)</h4>
            <div style="display: flex; flex-direction: column; gap: 0.4rem;">
              ${Object.entries(fixture.modelDerivedMarkets?.ht_ft || {}).slice(0, 5).map(([htft, prob]) => `
                <div style="display: flex; justify-content: space-between; font-size: 0.82rem; font-family: var(--font-mono);">
                  <span>${htft}:</span>
                  <span style="color: var(--accent-cyan); font-weight: 600;">${formatPercent(prob)}</span>
                  <span class="badge badge-slate" style="font-size: 0.68rem;">ODDS UNAVAILABLE</span>
                </div>
              `).join('')}
              ${(!fixture.modelDerivedMarkets?.ht_ft || Object.keys(fixture.modelDerivedMarkets.ht_ft).length === 0) ? `
                <div style="color: var(--text-muted); font-size: 0.8rem;">İY/MS projeksiyonu hesaplanıyor.</div>
              ` : ''}
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
}
