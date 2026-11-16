/**
 * Screen 6: Longshot Scanner
 * High-Odds & Underdog Variance Radar with Strict High-Odds != Value Separation
 */

import { selectAllEdges } from '../data/selectors.js';
import { formatOdds, formatPercent, formatSignedEdge } from '../data/normalizer.js';

export function renderLongshotScanner(state, minOddsThreshold = 5.0) {
  const allEdges = selectAllEdges(state);

  const longshots = allEdges.filter(e => {
    return typeof e.entry_odds === 'number' && e.entry_odds >= minOddsThreshold;
  }).sort((a, b) => b.entry_odds - a.entry_odds);

  return `
    <div class="longshot-scanner-view">
      <!-- High Odds != Value Warning Banner -->
      <div class="explainer-banner" style="background: rgba(245, 158, 11, 0.05); border-color: rgba(245, 158, 11, 0.3);">
        <div class="explainer-content">
          <div class="explainer-title" style="color: var(--accent-amber);">
            <span>🎯</span>
            <span>HIGH ODDS RADAR: HIGH ODDS ≠ VALUE SEPARATION</span>
          </div>
          <div class="explainer-text">
            Yüksek oranlı seçimler (Örn: 10.50) yüksek varyans taşır. Bu seçimlerin değerli sayılabilmesi için model olasılığının kitapçının marj arındırılmış adil olasılığından yüksek olması (pozitif raw edge) şarttır.
          </div>
        </div>
        <div class="banner-tags">
          <span class="badge badge-amber">HIGH ODDS (VARIANCE)</span>
          <span class="badge badge-emerald">VALUE (POSITIVE EDGE)</span>
        </div>
      </div>

      <!-- Filters -->
      <div class="filter-bar">
        <div class="filter-group">
          <span class="filter-label">Odds Tier:</span>
          <select class="filter-select" id="longshot-odds-filter">
            <option value="3.0" ${minOddsThreshold === 3.0 ? 'selected' : ''}>Odds ≥ 3.00</option>
            <option value="5.0" ${minOddsThreshold === 5.0 ? 'selected' : ''}>Odds ≥ 5.00 (Standard Longshot)</option>
            <option value="10.0" ${minOddsThreshold === 10.0 ? 'selected' : ''}>Odds ≥ 10.00 (Extreme Longshot)</option>
            <option value="20.0" ${minOddsThreshold === 20.0 ? 'selected' : ''}>Odds ≥ 20.00 (Moonshots)</option>
          </select>
        </div>
        <div class="filter-group">
          <span class="filter-label">Market:</span>
          <select class="filter-select" id="longshot-market-filter">
            <option value="ALL">All Quoted Markets (1X2, Totals)</option>
            <option value="1X2">1X2 Only</option>
          </select>
        </div>
      </div>

      <!-- Longshot Table -->
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">🎯 Longshot Selections with Bookmaker Evidence</span>
          <span class="badge badge-amber">${longshots.length} QUALIFYING SELECTIONS</span>
        </div>
        <table class="terminal-table">
          <thead>
            <tr>
              <th>Fixture</th>
              <th>Selection</th>
              <th>Bookmaker</th>
              <th>Entry Odds</th>
              <th>Market No-Vig</th>
              <th>Model Probability</th>
              <th>Model Fair Odds</th>
              <th>Raw Edge Status</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            ${longshots.length === 0 ? `
              <tr>
                <td colspan="9" style="text-align: center; padding: 3rem; color: var(--text-muted);">
                  <div style="font-family: var(--font-mono); font-size: 0.9rem;">NO QUALIFYING LONGSHOT</div>
                  <div style="font-size: 0.78rem; margin-top: 0.3rem;">No quoted selections currently exceed Odds ≥ ${minOddsThreshold.toFixed(2)}.</div>
                </td>
              </tr>
            ` : ''}
            ${longshots.map(l => {
              const isPositive = l.raw_edge > 0;
              return `
                <tr style="cursor: pointer;" data-fixture="${l.fixtureId}">
                  <td><strong>${l.homeTeam}</strong> vs ${l.awayTeam}</td>
                  <td>${l.selection_display}</td>
                  <td><span class="badge badge-slate">${l.bookmaker}</span></td>
                  <td><span class="badge badge-amber" style="font-size: 0.82rem;">${formatOdds(l.entry_odds)}</span></td>
                  <td class="mono-num" style="color: var(--accent-violet);">${formatPercent(l.market_no_vig)}</td>
                  <td class="mono-num" style="color: var(--accent-cyan); font-weight: 600;">${formatPercent(l.model_prob)}</td>
                  <td class="mono-num">${formatOdds(l.model_fair_odds)}</td>
                  <td>
                    <div style="display: flex; gap: 0.4rem; align-items: center;">
                      <span class="badge ${isPositive ? 'badge-emerald' : 'badge-rose'}">
                        ${formatSignedEdge(l.raw_edge)}
                      </span>
                      ${isPositive ? '<span class="badge badge-emerald" style="font-size: 0.65rem;">EDGE ADVANTAGE</span>' : '<span class="badge badge-slate" style="font-size: 0.65rem;">HIGH OVERROUND TRAP</span>'}
                    </div>
                  </td>
                  <td>
                    <button class="btn btn-outline" style="padding: 0.25rem 0.65rem; font-size: 0.75rem;" data-fixture="${l.fixtureId}">
                      Inspect →
                    </button>
                  </td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>

      <!-- Scope Limitation Notice on Correct Score -->
      <div class="panel" style="margin-top: 1.5rem; background: rgba(0,0,0,0.25); border: 1px dashed var(--border-subtle);">
        <div style="font-family: var(--font-mono); font-size: 0.78rem; color: var(--text-muted); line-height: 1.5;">
          ℹ️ <strong>LONGSHOT DATA INTEGRITY NOTICE:</strong> Correct Score ve HT/FT gibi yüksek varyanslı marketler modelimiz tarafından simüle edilmiştir; ancak mevcut snapshot'ta gerçek bookmaker oran kaydı bulunmadığı için bu ekrana sahte değer olarak yansıtılmamıştır. Yalnızca gerçek bookmaker kanıtı bulunan seçimler listelenir.
        </div>
      </div>
    </div>
  `;
}
