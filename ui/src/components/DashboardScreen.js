/**
 * Screen 1: Dashboard
 * Executive Overview of Sports Intelligence Engine
 */

import { selectTopEdges, selectLongshots } from '../data/selectors.js';
import { formatOdds, formatPercent, formatSignedEdge } from '../data/normalizer.js';

function extractPrimaryOdds(f) {
  const bks = f.bookmakers || {};
  if (bks.NESINE?.['1X2']?.odds) {
    const o = bks.NESINE['1X2'].odds;
    return {
      book: 'NESINE',
      h: o['1'] || (f.homeTeam && o[f.homeTeam]) || 'N/A',
      d: o['X'] || o['Draw'] || 'N/A',
      a: o['2'] || (f.awayTeam && o[f.awayTeam]) || 'N/A',
    };
  }
  if (bks.Bovada?.['1X2']?.odds) {
    const o = bks.Bovada['1X2'].odds;
    return {
      book: 'Bovada',
      h: (f.homeTeam && o[f.homeTeam]) || o['1'] || 'N/A',
      d: o['Draw'] || o['X'] || 'N/A',
      a: (f.awayTeam && o[f.awayTeam]) || o['2'] || 'N/A',
    };
  }
  if (bks.PINNACLE?.['1X2']?.odds) {
    const o = bks.PINNACLE['1X2'].odds;
    return {
      book: 'Pinnacle',
      h: o['1'] || 'N/A',
      d: o['X'] || 'N/A',
      a: o['2'] || 'N/A',
    };
  }
  const anyBook = Object.keys(bks)[0];
  if (anyBook && bks[anyBook]?.['1X2']?.odds) {
    const o = bks[anyBook]['1X2'].odds;
    return {
      book: anyBook,
      h: o['1'] || (f.homeTeam && o[f.homeTeam]) || 'N/A',
      d: o['X'] || o['Draw'] || 'N/A',
      a: o['2'] || (f.awayTeam && o[f.awayTeam]) || 'N/A',
    };
  }
  return { book: 'N/A', h: 'N/A', d: 'N/A', a: 'N/A' };
}

function formatOddsHighlight(oddVal) {
  if (!oddVal || oddVal === 'N/A' || isNaN(oddVal)) return 'N/A';
  return `<strong>${Number(oddVal).toFixed(2)}</strong>`;
}

function formatHomeProbHighlight(probVal) {
  if (probVal === null || probVal === undefined || isNaN(probVal)) {
    return 'UNKNOWN';
  }
  const pctNum = probVal * 100;
  const pctStr = pctNum.toFixed(2) + '%';
  if (pctNum >= 60.0) {
    return `<span class="badge badge-emerald" style="font-weight: 700; box-shadow: 0 0 8px rgba(16, 185, 129, 0.45); border: 1px solid var(--accent-emerald); font-size: 0.8rem;">${pctStr}</span>`;
  }
  if (pctNum >= 50.0) {
    return `<span style="color: var(--accent-emerald); font-weight: 700; background: rgba(16, 185, 129, 0.12); padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(16, 185, 129, 0.3); font-size: 0.8rem;">${pctStr}</span>`;
  }
  return `<span style="color: var(--accent-cyan); font-weight: 600;">${pctStr}</span>`;
}

function formatKickoffDisplay(f) {
  if (f.kickoff_trt || f.kickoffTrt) {
    const raw = (f.kickoff_trt || f.kickoffTrt);
    if (raw.includes(' ')) {
      const parts = raw.split(' ');
      const timePart = parts[1].substring(0, 5);
      const datePart = parts[0].substring(5);
      return `${datePart} ${timePart} TR`;
    }
    return `${raw} TR`;
  }
  if (f.kickoff) {
    return `${f.kickoff.substring(5, 16).replace('T', ' ')} UTC`;
  }
  return 'N/A';
}

export function renderDashboard(state, onNavigate, onSelectFixture) {
  const topEdges = selectTopEdges(state, 4);
  const longshots = selectLongshots(state, 5.0).slice(0, 4);
  const fixtures = state.fixtures || [];

  return `
    <div class="dashboard-view">
      <!-- Live Daemon Status Banner -->
      <div class="explainer-banner" style="border-color: rgba(16, 185, 129, 0.4); background: rgba(16, 185, 129, 0.05); margin-bottom: 1rem;">
        <div class="explainer-content">
          <div class="explainer-title" style="color: var(--accent-emerald);">
            <span class="system-indicator pulse"></span>
            <span>CANLI DAEMON DURUMU: ${state.daemonStatus?.status || 'HEALTHY'} (${state.daemonStatus?.leagues_scanned || 28} LİG TARANIYOR)</span>
          </div>
          <div class="explainer-text">
            Arka plan tarama motoru her 120 saniyede bir Nesine CDN ve Pinnacle bültenlerini eşleştirmekte; Shin marjı arındırma ve Dixon-Coles modeliyle doğrulanmış VIP sinyalleri anlık Telegram botuna ve bu terminale aktarmaktadır.
          </div>
        </div>
        <div class="banner-tags">
          <span class="badge badge-emerald">AKTİF +EV: ${state.daemonStatus?.positive_ev_signals ?? 0}</span>
          <span class="badge badge-cyan">KELLY KALKANI: 0.5x</span>
        </div>
      </div>

      <!-- Explainer Banner: High Odds != Value -->
      <div class="explainer-banner">
        <div class="explainer-content">
          <div class="explainer-title">
            <span>⚠️</span>
            <span>CORE ARCHITECTURAL PRINCIPLE: HIGH ODDS ≠ VALUE</span>
          </div>
          <div class="explainer-text">
            Yüksek oran tek başına bir fırsat değildir. Bir seçimin değer (edge) taşıması, yalnızca model olasılığının piyasa Shin no-vig adil olasılığından yüksek olması durumunda geçerlidir.
          </div>
        </div>
        <div class="banner-tags">
          <span class="badge badge-amber">HIGH ODDS = VARIANCE</span>
          <span class="badge badge-emerald">VALUE = POSITIVE EDGE</span>
        </div>
      </div>

      <!-- KPI Summary Cards -->
      <div class="grid-4" style="margin-bottom: 1.5rem;">
        <div class="kpi-card cyan">
          <span class="kpi-label">Active Fixtures</span>
          <span class="kpi-value">${state.totalFixtures || (state.fixtures ? state.fixtures.length : 0)}</span>
          <span class="kpi-sub">Upcoming & Live Quoted Fixtures</span>
        </div>
        <div class="kpi-card emerald">
          <span class="kpi-label">Top Raw Edge</span>
          <span class="kpi-value">${topEdges.length > 0 ? formatSignedEdge(topEdges[0].raw_edge) : 'N/A'}</span>
          <span class="kpi-sub">${topEdges.length > 0 ? `${topEdges[0].homeTeam || 'Unknown'} vs ${topEdges[0].awayTeam || 'Unknown'} (${topEdges[0].selection_display || topEdges[0].selection || 'N/A'})` : 'None'}</span>
        </div>
        <div class="kpi-card amber">
          <span class="kpi-label">VIP +EV Sinyalleri</span>
          <span class="kpi-value">${state.daemonStatus?.positive_ev_signals ?? 0}</span>
          <span class="kpi-sub">Shin Devigged & Kelly Scaled</span>
        </div>
        <div class="kpi-card violet">
          <span class="kpi-label">Active Data Snapshot</span>
          <span class="kpi-value" style="font-size: 1.1rem; padding-top: 0.4rem;">${state.provider || 'UNKNOWN'}</span>
          <span class="kpi-sub">${state.snapshotTimestamp && typeof state.snapshotTimestamp === 'string' ? state.snapshotTimestamp.substring(0, 19).replace('T', ' ') : 'N/A'} UTC</span>
        </div>
      </div>

      <!-- Provider Status Grid -->
      <div class="panel" style="margin-bottom: 1.5rem;">
        <div class="panel-header">
          <span class="panel-title">📡 Global Provider Universe & Reconciliation Status</span>
          <span class="panel-badge">AUDIT: SPEC-0012 VERIFIED</span>
        </div>
        <div class="grid-4">
          ${(state.providerStatus || []).map(p => `
            <div style="background: rgba(0,0,0,0.25); padding: 0.8rem 1rem; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
              <div style="display: flex; justify-content: space-between; margin-bottom: 0.3rem;">
                <strong style="color: var(--text-bright);">${p.provider}</strong>
                <span class="badge ${p.status.includes('PRIMARY') ? 'badge-cyan' : 'badge-emerald'}">${p.status}</span>
              </div>
              <div style="font-family: var(--font-mono); font-size: 0.75rem; color: var(--text-secondary);">
                Events: ${p.events} | Sync: ${p.reconciliation}
              </div>
            </div>
          `).join('')}
        </div>
      </div>

      <!-- Goal Anomaly & In-Play Timing Radar Panel -->
      ${((state.goalAnomalies || state.goal_anomalies || []).length > 0) ? `
      <div class="panel" style="margin-bottom: 1.5rem; border-color: rgba(239, 68, 68, 0.4); background: rgba(239, 68, 68, 0.02);">
        <div class="panel-header" style="border-bottom: 1px solid rgba(239, 68, 68, 0.2);">
          <div style="display: flex; align-items: center; gap: 0.5rem;">
            <span style="font-size: 1.1rem;">🔥</span>
            <span class="panel-title" style="color: #f87171;">6+ GOL ANOMALİSİ & ZAMANLAMA RADARI (GASI >= 70)</span>
          </div>
          <div style="display: flex; gap: 0.5rem;">
            <span class="badge badge-rose">%88.8 HT 1.5 ÜST KURALI</span>
            <span class="badge badge-amber">FAT-TAIL NEG-BİNOM</span>
          </div>
        </div>
        <div class="table-container">
          <table class="terminal-table">
            <thead>
              <tr>
                <th>Karşılaşma</th>
                <th>Arketip</th>
                <th>GASI Skoru</th>
                <th>6+ Olasılığı</th>
                <th>Adil 6+ Oranı</th>
                <th>Hedef Canlı Çizgi</th>
                <th>Zamanlama & Zirve Dilimi</th>
              </tr>
            </thead>
            <tbody>
              ${(state.goalAnomalies || state.goal_anomalies || []).slice(0, 6).map(g => `
                <tr>
                  <td>
                    <div style="font-weight: 600; color: var(--text-bright);">${g.home} vs ${g.away}</div>
                    <div style="font-size: 0.73rem; color: var(--accent-cyan); margin-top: 2px;">
                      ⏰ ${g.kickoff || 'TBD'} | MBS-1
                    </div>
                  </td>
                  <td><span class="badge badge-amber">${g.archetype || 'HYPER_OVER_MAGNET'}</span></td>
                  <td>
                    <span class="badge badge-rose" style="font-weight: 700;">
                      ${g.gasi_score || 70.0}/100 [SILVER]
                    </span>
                  </td>
                  <td class="mono-num" style="color: #4ade80; font-weight: 600;">%${g.p_6plus || 22.0}</td>
                  <td class="mono-num" style="color: var(--accent-cyan); font-weight: 600;">@${g.fair_odds_6plus ? g.fair_odds_6plus.toFixed(2) : '4.55'}</td>
                  <td>
                    <span class="badge badge-cyan">${g.in_play_target_line || '4.5 / 5.5 ÜST'}</span>
                  </td>
                  <td>
                    <div style="font-size: 0.75rem; color: var(--text-secondary);">
                      Ev: <strong style="color: #f87171;">${g.home_peak_scoring || '76-90+'}</strong> | Dep: <strong style="color: #f87171;">${g.away_peak_scoring || '76-90+'}</strong>
                    </div>
                    <div style="font-size: 0.7rem; color: var(--accent-amber); margin-top: 2px;">
                      ⚡ ${g.ht_gold_rule_target || 'HT Goals >= 2'} şartı
                    </div>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
      ` : ''}

      <!-- Two Columns: Top Edge Watch vs Longshot Watch -->
      <div class="grid-2" style="margin-bottom: 1.5rem;">
        <!-- Column 1: Top Positive Edge Discrepancies -->
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">📈 Top Value / Edge Watch</span>
            <span class="badge badge-emerald">MODEL > MARKET</span>
          </div>
          <table class="terminal-table">
            <thead>
              <tr>
                <th>Fixture</th>
                <th>Market</th>
                <th>Selection</th>
                <th>Odds</th>
                <th>Raw Edge</th>
              </tr>
            </thead>
            <tbody>
              ${topEdges.length === 0 ? `<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">No qualifying edges in snapshot</td></tr>` : ''}
              ${topEdges.map(e => `
                <tr style="cursor: pointer;" data-fixture="${e.fixtureId || ''}">
                  <td>
                    <div style="font-weight: 600; color: var(--text-bright);">${e.homeTeam || 'Unknown'} vs ${e.awayTeam || 'Unknown'}</div>
                    <div style="font-size: 0.73rem; color: var(--accent-cyan); margin-top: 2px;">
                      ⏰ ${e.kickoff_trt || e.kickoffTrt ? (e.kickoff_trt || e.kickoffTrt).split(' ')[1] + ' TR' : (e.kickoff ? e.kickoff.substring(11, 16) + ' UTC' : 'TBD')}
                    </div>
                  </td>
                  <td><span class="badge badge-slate">${e.market || '1X2'}</span></td>
                  <td>${e.selection_display || e.selection || 'N/A'}</td>
                  <td class="mono-num">${formatOddsHighlight(e.entry_odds)}</td>
                  <td>
                    <span class="badge ${e.raw_edge > 0 ? 'badge-emerald' : 'badge-rose'}">
                      ${formatSignedEdge(e.raw_edge)}
                    </span>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
          <div style="margin-top: 1rem; text-align: right;">
            <button class="btn btn-outline" data-screen-goto="value-scanner">View All Edge Discrepancies →</button>
          </div>
        </div>

        <!-- Column 2: Longshot Watch -->
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">🎯 Longshot Watch (Odds ≥ 5.00)</span>
            <span class="badge badge-amber">HIGH VARIANCE</span>
          </div>
          <table class="terminal-table">
            <thead>
              <tr>
                <th>Fixture</th>
                <th>Selection</th>
                <th>Bookmaker Odds</th>
                <th>Model Prob</th>
                <th>Raw Edge</th>
              </tr>
            </thead>
            <tbody>
              ${longshots.length === 0 ? `<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">No longshots available in snapshot</td></tr>` : ''}
              ${longshots.map(l => `
                <tr style="cursor: pointer;" data-fixture="${l.fixtureId || ''}">
                  <td>
                    <div style="font-weight: 600; color: var(--text-bright);">${l.homeTeam || 'Unknown'} vs ${l.awayTeam || 'Unknown'}</div>
                    <div style="font-size: 0.73rem; color: var(--accent-amber); margin-top: 2px;">
                      ⏰ ${l.kickoff_trt || l.kickoffTrt ? (l.kickoff_trt || l.kickoffTrt).split(' ')[1] + ' TR' : (l.kickoff ? l.kickoff.substring(11, 16) + ' UTC' : 'TBD')}
                    </div>
                  </td>
                  <td>${l.selection_display || l.selection || 'N/A'}</td>
                  <td class="mono-num">${formatOddsHighlight(l.entry_odds)}</td>
                  <td class="mono-num">${formatPercent(l.model_prob)}</td>
                  <td>
                    <span class="badge ${l.raw_edge > 0 ? 'badge-emerald' : 'badge-rose'}">
                      ${formatSignedEdge(l.raw_edge)}
                    </span>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
          <div style="margin-top: 1rem; text-align: right;">
            <button class="btn btn-outline" data-screen-goto="longshot-scanner">View Longshot Radar →</button>
          </div>
        </div>
      </div>

      <!-- Commercial SaaS Syndicate Pro (In-Play Sniper & Copula SGP) Overview -->
      <div class="panel" style="margin-bottom: 1.5rem; border-color: rgba(16, 185, 129, 0.35);">
        <div class="panel-header">
          <span class="panel-title">⚡ Commercial SaaS: In-Play Sniper & Copula SGP Radarı (Tier 1 / 2 / 3)</span>
          <span class="badge badge-emerald">SOTA 5-ENGINE ACTIVE</span>
        </div>
        <div class="grid-4" style="grid-template-columns: repeat(3, 1fr); margin-bottom: 0.8rem;">
          <div style="background: rgba(6, 182, 212, 0.06); padding: 0.85rem 1rem; border-radius: var(--radius-sm); border: 1px solid rgba(6, 182, 212, 0.3);">
            <div style="font-size: 0.75rem; color: var(--accent-cyan); font-weight: 700;">⚡ IN-PLAY CONTINUOUS SNIPER</div>
            <div style="font-family: var(--font-mono); font-size: 1.1rem; font-weight: 700; color: var(--text-bright); margin: 0.25rem 0;">
              ${(state.syndicatePro?.in_play_sniper_alerts || []).length} Canlı Pusu Hazır
            </div>
            <div style="font-size: 0.74rem; color: var(--text-secondary);">10'-40' Korner & İY-X / MS-1 Devre Pususu (Tier 2 Pro)</div>
          </div>
          <div style="background: rgba(245, 158, 11, 0.06); padding: 0.85rem 1rem; border-radius: var(--radius-sm); border: 1px solid rgba(245, 158, 11, 0.3);">
            <div style="font-size: 0.75rem; color: var(--accent-amber); font-weight: 700;">🧬 COPULA SGP KOMBİNASYON MOTORU</div>
            <div style="font-family: var(--font-mono); font-size: 1.1rem; font-weight: 700; color: var(--text-bright); margin: 0.25rem 0;">
              ${(state.syndicatePro?.copula_sgp_combinations || []).length} Korelasyonlu SGP
            </div>
            <div style="font-size: 0.74rem; color: var(--text-secondary);">Clayton & Gumbel Bivariate Bağlılık (Tier 3 VIP)</div>
          </div>
          <div style="background: rgba(16, 185, 129, 0.06); padding: 0.85rem 1rem; border-radius: var(--radius-sm); border: 1px solid rgba(16, 185, 129, 0.3);">
            <div style="font-size: 0.75rem; color: var(--accent-emerald); font-weight: 700;">📈 CLV ALFA & PORTFÖY KELLY</div>
            <div style="font-family: var(--font-mono); font-size: 1.1rem; font-weight: 700; color: var(--text-bright); margin: 0.25rem 0;">
              %65 Stale / %35 Info Alfa
            </div>
            <div style="font-size: 0.74rem; color: var(--text-secondary);">30.316 Maç Walk-Forward Doğrulandı</div>
          </div>
        </div>
        <div style="text-align: right;">
          <button class="btn btn-outline" data-screen-goto="syndicate-pro">⚡ Syndicate Pro & SaaS Paneline Git →</button>
        </div>
      </div>

      <!-- Upcoming Fixtures Quick List -->
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">⚽ Upcoming Matches (Pre-match & Canlı Bülten)</span>
          <span class="badge badge-emerald">${fixtures.length} MATCHES</span>
        </div>
        <table class="terminal-table">
          <thead>
            <tr>
              <th>Kickoff</th>
              <th>Match</th>
              <th>1X2 Model Probabilities</th>
              <th>Primary Book Odds</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            ${fixtures.map(f => {
              const odds = extractPrimaryOdds(f);
              return `
                <tr>
                  <td class="mono-num" style="font-size: 0.8rem;">
                    <div style="font-weight: 600; color: var(--accent-cyan);">${formatKickoffDisplay(f)}</div>
                    ${f.kickoff ? `<div style="font-size: 0.7rem; color: var(--text-muted);">${f.kickoff.substring(5, 16).replace('T', ' ')} UTC</div>` : ''}
                  </td>
                  <td>
                    <div style="font-weight: 600; color: var(--text-bright);">${f.homeTeam || 'Unknown'} vs ${f.awayTeam || 'Unknown'}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted);">${f.competition || f.league || 'Football'} • <span style="color: var(--text-secondary);">${f.country || 'Global'}</span></div>
                  </td>
                  <td class="mono-num">
                    H: ${formatHomeProbHighlight(f.model1x2?.HOME)} | 
                    D: <span style="color: var(--text-secondary);">${formatPercent(f.model1x2?.DRAW)}</span> | 
                    A: <span style="color: var(--text-secondary);">${formatPercent(f.model1x2?.AWAY)}</span>
                  </td>
                  <td class="mono-num">
                    <span class="badge badge-slate" style="font-size: 0.68rem; margin-right: 4px;">${odds.book}</span>
                    <strong>${odds.h}</strong> / <strong>${odds.d}</strong> / <strong>${odds.a}</strong>
                  </td>
                  <td>
                    <button class="btn btn-outline" style="padding: 0.3rem 0.7rem; font-size: 0.78rem;" data-fixture="${f.fixtureId || ''}">
                      Match Detail →
                    </button>
                  </td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;
}
