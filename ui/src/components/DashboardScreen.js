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

function extractMarginBadge(f) {
  const nes = f.bookmakers?.NESINE?.['1X2'];
  if (nes?.overround && !isNaN(nes.overround)) {
    const pct = (Number(nes.overround) * 100).toFixed(1);
    return `<span class="badge badge-amber">Marj %${pct}</span>`;
  }
  const o = nes?.odds;
  if (o && o['1'] && o['X'] && o['2']) {
    const ov = (1 / Number(o['1']) + 1 / Number(o['X']) + 1 / Number(o['2'])) * 100;
    if (!isNaN(ov) && ov > 0) {
      return `<span class="badge badge-amber">Marj %${ov.toFixed(1)}</span>`;
    }
  }
  return '<span class="badge badge-slate">Dünya / Bülten</span>';
}

export function renderDashboard(state, onNavigate, onSelectFixture) {
  const topEdges = selectTopEdges(state, 4);
  const longshots = selectLongshots(state, 5.0).slice(0, 4);
  const fixtures = state.fixtures || [];

  return `
    <div class="dashboard-view">
      <!-- Live Pipeline Status Banner -->
      <div class="explainer-banner" style="border-color: rgba(16, 185, 129, 0.4); background: rgba(16, 185, 129, 0.05); margin-bottom: 1rem;">
        <div class="explainer-content">
          <div class="explainer-title" style="color: var(--accent-emerald);">
            <span class="system-indicator pulse"></span>
            <span>OTOMATİK TARAMA: GÜNLÜK NESİNE CDN &amp; ESPN/DRAFTKINGS ADİL ORAN TERMİNALİ</span>
          </div>
          <div class="explainer-text">
            Günde 3 kez (11:00, 15:00, 19:00 TR) Nesine bülteni ile dünya keskin piyasa oranları (Shin no-vig arındırma) kıyaslanır; yalnızca doğrulanmış pozitif değerli (+EV) fırsatlar ve marj analizleri Telegram özetine aktarılır.
          </div>
        </div>
        <div class="banner-tags">
          <span class="badge badge-emerald">DOĞRULANMIŞ +EV: ${state.daemonStatus?.positive_ev_signals ?? 0}</span>
          <span class="badge badge-cyan">KELLY KALKANI: 0.5x</span>
        </div>
      </div>

      <!-- Explainer Banner: High Odds != Value -->
      <div class="explainer-banner">
        <div class="explainer-content">
          <div class="explainer-title">
            <span>⚠️</span>
            <span>TEMEL KURAL: YÜKSEK ORAN ≠ DEĞER FIRSATI</span>
          </div>
          <div class="explainer-text">
            Yüksek oran tek başına fırsat değildir. Bir seçimin matematiksel değer taşıması için Nesine oranının dünya piyasası Shin arındırılmış adil oranından yüksek olması gerekir.
          </div>
        </div>
        <div class="banner-tags">
          <span class="badge badge-amber">YÜKSEK ORAN = RİSK</span>
          <span class="badge badge-emerald">DEĞER = POZİTİF FARK</span>
        </div>
      </div>

      <!-- KPI Summary Cards -->
      <div class="grid-4" style="margin-bottom: 1.5rem;">
        <div class="kpi-card cyan">
          <span class="kpi-label">Aktif Fikstür</span>
          <span class="kpi-value">${state.totalFixtures || (state.fixtures ? state.fixtures.length : 0)}</span>
          <span class="kpi-sub">Yaklaşan Bülten Maçları</span>
        </div>
        <div class="kpi-card emerald">
          <span class="kpi-label">En İyi Ham Fark</span>
          <span class="kpi-value">${topEdges.length > 0 ? formatSignedEdge(topEdges[0].raw_edge) : '0 / Yok'}</span>
          <span class="kpi-sub">${topEdges.length > 0 ? `${topEdges[0].homeTeam || 'Unknown'} vs ${topEdges[0].awayTeam || 'Unknown'} (${topEdges[0].selection_display || topEdges[0].selection || 'N/A'})` : 'Keskin piyasa vetosu'}</span>
        </div>
        <div class="kpi-card amber">
          <span class="kpi-label">Doğrulanmış +EV</span>
          <span class="kpi-value">${state.daemonStatus?.positive_ev_signals ?? 0}</span>
          <span class="kpi-sub">Shin Arındırılmış &amp; Kelly Onaylı</span>
        </div>
        <div class="kpi-card violet">
          <span class="kpi-label">Son Güncelleme</span>
          <span class="kpi-value" style="font-size: 1.05rem; padding-top: 0.4rem;">${state.provider || 'NESINE + ESPN'}</span>
          <span class="kpi-sub">${state.snapshotTimestamp && typeof state.snapshotTimestamp === 'string' ? state.snapshotTimestamp.substring(0, 19).replace('T', ' ') : 'N/A'} UTC</span>
        </div>
      </div>

      <!-- Provider Status Grid -->
      <div class="panel" style="margin-bottom: 1.5rem;">
        <div class="panel-header">
          <span class="panel-title">📡 Veri Sağlayıcıları ve Senkronizasyon Durumu</span>
          <span class="panel-badge">DENETİM: SPEC-0012 DOĞRULANDI</span>
        </div>
        <div class="grid-4">
          ${(state.providerStatus || []).map(p => `
            <div style="background: rgba(0,0,0,0.25); padding: 0.8rem 1rem; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
              <div style="display: flex; justify-content: space-between; margin-bottom: 0.3rem;">
                <strong style="color: var(--text-bright);">${p.provider}</strong>
                <span class="badge ${p.status.includes('PRIMARY') ? 'badge-cyan' : 'badge-emerald'}">${p.status}</span>
              </div>
              <div style="font-family: var(--font-mono); font-size: 0.75rem; color: var(--text-secondary);">
                Maç: ${p.events} | Durum: ${p.reconciliation}
              </div>
            </div>
          `).join('')}
        </div>
      </div>

      <!-- Two Columns: Top Edge Watch vs Longshot Watch -->
      <div class="grid-2" style="margin-bottom: 1.5rem;">
        <!-- Column 1: Top Positive Edge Discrepancies -->
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">📈 En Yakın Değer / Oran Farkları</span>
            <span class="badge badge-emerald">NESİNE vs ADİL ORAN</span>
          </div>
          <table class="terminal-table">
            <thead>
              <tr>
                <th>Karşılaşma</th>
                <th>Market</th>
                <th>Seçim</th>
                <th>Oran</th>
                <th>Fark</th>
              </tr>
            </thead>
            <tbody>
              ${topEdges.length === 0 ? `<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">Bu taramada pozitif +EV adayı bulunmadı</td></tr>` : ''}
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
            <button class="btn btn-outline" data-screen-goto="value-scanner">Tüm Oran Farklarını Gör →</button>
          </div>
        </div>

        <!-- Column 2: Longshot Watch -->
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">🎯 Sürpriz Oran Takibi (Oran ≥ 5.00)</span>
            <span class="badge badge-amber">YÜKSEK VARYANS</span>
          </div>
          <table class="terminal-table">
            <thead>
              <tr>
                <th>Karşılaşma</th>
                <th>Seçim</th>
                <th>Nesine Oranı</th>
                <th>Model Olasılığı</th>
                <th>Fark</th>
              </tr>
            </thead>
            <tbody>
              ${longshots.length === 0 ? `<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">Bu bültende kriterlere uyan sürpriz oran yok</td></tr>` : ''}
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
            <button class="btn btn-outline" data-screen-goto="longshot-scanner">Sürpriz Tarayıcıyı Aç →</button>
          </div>
        </div>
      </div>

      <!-- Upcoming Fixtures Quick List -->
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">⚽ Yaklaşan Maçlar (Nesine 1X2 Oranları &amp; Komisyon Marjı)</span>
          <span class="badge badge-emerald">${fixtures.length} MAÇ</span>
        </div>
        <table class="terminal-table">
          <thead>
            <tr>
              <th>Başlama Saati</th>
              <th>Karşılaşma</th>
              <th>Model Olasılığı / Kasa Marjı</th>
              <th>1X2 Bülten Oranları</th>
              <th>Detay</th>
            </tr>
          </thead>
          <tbody>
            ${fixtures.map(f => {
              const odds = extractPrimaryOdds(f);
              const hasModel = f.model1x2?.HOME !== null && f.model1x2?.HOME !== undefined && !isNaN(f.model1x2?.HOME);
              const thirdCol = hasModel
                ? `MS1: ${formatHomeProbHighlight(f.model1x2?.HOME)} | X: <span style="color: var(--text-secondary);">${formatPercent(f.model1x2?.DRAW)}</span> | MS2: <span style="color: var(--text-secondary);">${formatPercent(f.model1x2?.AWAY)}</span>`
                : extractMarginBadge(f);
              return `
                <tr>
                  <td class="mono-num" style="font-size: 0.8rem;">
                    <div style="font-weight: 600; color: var(--accent-cyan);">${formatKickoffDisplay(f)}</div>
                    ${f.kickoff ? `<div style="font-size: 0.7rem; color: var(--text-muted);">${f.kickoff.substring(5, 16).replace('T', ' ')} UTC</div>` : ''}
                  </td>
                  <td>
                    <div style="font-weight: 600; color: var(--text-bright);">${f.homeTeam || 'Unknown'} vs ${f.awayTeam || 'Unknown'}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted);">${f.competition || f.league || 'Futbol'} • <span style="color: var(--text-secondary);">${f.country || 'Global'}</span></div>
                  </td>
                  <td class="mono-num">
                    ${thirdCol}
                  </td>
                  <td class="mono-num">
                    <span class="badge badge-slate" style="font-size: 0.68rem; margin-right: 4px;">${odds.book}</span>
                    <strong>${odds.h}</strong> / <strong>${odds.d}</strong> / <strong>${odds.a}</strong>
                  </td>
                  <td>
                    <button class="btn btn-outline" style="padding: 0.3rem 0.7rem; font-size: 0.78rem;" data-fixture="${f.fixtureId || ''}">
                      Maç Detayı →
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
