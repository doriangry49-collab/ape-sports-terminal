/**
 * Screen 4: Market Explorer
 * Market-centric aggregation across all fixtures for 1X2, Totals, and BTTS
 */

import { selectAllEdges } from '../data/selectors.js';
import { formatOdds, formatPercent, formatSignedEdge } from '../data/normalizer.js';

export function renderMarketExplorer(state, currentMarket = '1X2') {
  const allEdges = selectAllEdges(state);
  const filteredEdges = allEdges.filter(e => e.market === currentMarket);

  return `
    <div class="market-explorer-view">
      <div class="filter-bar">
        <div class="filter-group">
          <span class="filter-label">Market Focus:</span>
          <select class="filter-select" id="market-select">
            <option value="1X2" ${currentMarket === '1X2' ? 'selected' : ''}>1X2 (Match Winner)</option>
            <option value="TOTALS" ${currentMarket === 'TOTALS' ? 'selected' : ''}>TOTALS (Over/Under 2.5)</option>
            <option value="BTTS" ${currentMarket === 'BTTS' ? 'selected' : ''}>BTTS (Both Teams To Score)</option>
          </select>
        </div>
        <div class="filter-group">
          <span class="filter-label">Primary Bookmaker:</span>
          <select class="filter-select" id="bookmaker-filter">
            <option value="ALL">All Available Books</option>
            <option value="Bovada" selected>Bovada (Primary Outcome Timestamps)</option>
            <option value="Pinnacle">Pinnacle</option>
          </select>
        </div>
      </div>

      ${currentMarket === 'BTTS' ? `
        <div class="panel" style="text-align: center; padding: 3rem 2rem; border: 1px dashed var(--accent-amber);">
          <div style="font-size: 2rem; margin-bottom: 0.8rem;">⚡</div>
          <h3 style="color: var(--accent-amber); font-size: 1.15rem; margin-bottom: 0.5rem;">BTTS Bookmaker Market Data Unavailable</h3>
          <p style="color: var(--text-secondary); max-width: 600px; margin: 0 auto; font-size: 0.88rem; line-height: 1.5;">
            Poisson modelimiz tüm maçlar için BTTS projeksiyonları üretmiştir; ancak mevcut PropLine bulk odds snapshot dosyasında bookmaker oran kaydı bulunmamaktadır.
          </p>
          <div style="margin-top: 1.5rem;">
            <span class="badge badge-slate">MODEL COVERAGE: YES (100%)</span>
            <span class="badge badge-amber" style="margin-left: 0.5rem;">ODDS COVERAGE: 0% (NO_DATA)</span>
          </div>
        </div>
      ` : `
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">📋 Market Selections: ${currentMarket}</span>
            <span class="badge badge-cyan">${filteredEdges.length} SELECTIONS OBSERVED</span>
          </div>
          <table class="terminal-table">
            <thead>
              <tr>
                <th>Fixture</th>
                <th>Selection</th>
                <th>Bookmaker</th>
                <th>Entry Odds</th>
                <th>Overround</th>
                <th>No-Vig (Fair Mkt)</th>
                <th>Model Prob</th>
                <th>Model Fair Odds</th>
                <th>Raw Edge</th>
              </tr>
            </thead>
            <tbody>
              ${filteredEdges.length === 0 ? `<tr><td colspan="9" style="text-align:center; color:var(--text-muted);">No selections available for this market</td></tr>` : ''}
              ${filteredEdges.map(e => `
                <tr style="cursor: pointer;" data-fixture="${e.fixtureId}">
                  <td><strong>${e.homeTeam}</strong> vs ${e.awayTeam}</td>
                  <td>${e.selection_display}</td>
                  <td><span class="badge badge-slate">${e.bookmaker}</span></td>
                  <td class="mono-num"><strong>${formatOdds(e.entry_odds)}</strong></td>
                  <td class="mono-num">${formatPercent(e.overround - 1.0)}</td>
                  <td class="mono-num" style="color: var(--accent-violet);">${formatPercent(e.market_no_vig)}</td>
                  <td class="mono-num" style="color: var(--accent-cyan); font-weight: 600;">${formatPercent(e.model_prob)}</td>
                  <td class="mono-num">${formatOdds(e.model_fair_odds)}</td>
                  <td>
                    <span class="badge ${e.raw_edge > 0 ? 'badge-emerald' : 'badge-rose'}">
                      ${formatSignedEdge(e.raw_edge)}
                    </span>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `}
    </div>
  `;
}
