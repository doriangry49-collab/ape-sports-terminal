/**
 * Screen 5: Value / Edge Scanner
 * Analytical Model vs Market Discrepancy Finder
 * Equipped with Shin Devigging, EV ROI, and Half-Kelly position sizing.
 */

import { selectAllEdges } from '../data/selectors.js';
import { formatOdds, formatPercent, formatSignedEdge, formatEvRoi, formatKellyStake, formatVig } from '../data/normalizer.js';

function normalizeLeagueText(text) {
  if (!text || typeof text !== 'string') return '';
  return text.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').trim().toLowerCase();
}

export function renderValueScanner(
  state,
  minEvFilter = 0.0,
  minProbFilter = 0.0,
  selectedLeague = 'all',
  selectedBookmaker = 'all'
) {
  let minEv = minEvFilter;
  let minProb = minProbFilter;
  let league = selectedLeague;
  let bookmaker = selectedBookmaker;

  // Flexible parameter ingestion (positional, options object, or state.filters)
  if (typeof minEvFilter === 'object' && minEvFilter !== null) {
    minEv = minEvFilter.minEv ?? minEvFilter.minEdge ?? 0.0;
    minProb = minEvFilter.minProb ?? 0.0;
    league = minEvFilter.league ?? 'all';
    bookmaker = minEvFilter.bookmaker ?? 'all';
  } else if (state?.filters) {
    if (minEv === 0.0 && state.filters.minEv !== undefined) minEv = state.filters.minEv;
    if (minProb === 0.0 && state.filters.minProb !== undefined) minProb = state.filters.minProb;
    if (league === 'all' && state.filters.league !== undefined) league = state.filters.league;
    if (bookmaker === 'all' && state.filters.bookmaker !== undefined) bookmaker = state.filters.bookmaker;
  }

  const allEdges = selectAllEdges(state);

  // Dynamically extract all distinct leagues from active snapshot edges and fixtures
  const leagueSet = new Set();
  for (const e of allEdges) {
    const lg = e.league || e.competition;
    if (lg && typeof lg === 'string' && lg.trim() && lg !== 'UNKNOWN') {
      leagueSet.add(lg.trim());
    }
  }
  if (state?.fixtures) {
    for (const f of state.fixtures) {
      const lg = f.competition || f.league;
      if (lg && typeof lg === 'string' && lg.trim() && lg !== 'UNKNOWN') {
        leagueSet.add(lg.trim());
      }
    }
  }
  const availableLeagues = Array.from(leagueSet).sort((a, b) => a.localeCompare(b));

  // Determine uniform EV ROI threshold
  let minEvThreshold = -999999;
  let minEvSelectedStr = '0.0';

  if (minEv === 'all' || minEv === 'ALL') {
    minEvThreshold = -999999;
    minEvSelectedStr = 'all';
  } else if (typeof minEv === 'number' || (typeof minEv === 'string' && !isNaN(parseFloat(minEv)))) {
    const n = parseFloat(minEv);
    if (n > 0 && n < 1.0) {
      // Decimal representation (e.g. 0.03 -> 3.0%, 0.05 -> 5.0%, 0.08 -> 8.0%)
      minEvThreshold = n * 100.0;
      minEvSelectedStr = (n * 100.0).toFixed(1);
    } else {
      minEvThreshold = n;
      minEvSelectedStr = n.toFixed(1);
    }
  }

  const minProbNum = parseFloat(minProb) || 0.0;
  const activeLeague = (league || 'all').trim();
  const activeBookmaker = (bookmaker || 'all').trim();

  // Filter edges uniformly
  const filtered = allEdges.filter(e => {
    const rawEdge = typeof e.raw_edge === 'number' ? e.raw_edge : -999;
    const modelP = typeof e.model_prob === 'number' ? e.model_prob : 0;
    const evRoi = typeof e.evRoi === 'number' ? e.evRoi : (typeof e.ev_roi === 'number' ? e.ev_roi : (rawEdge * 100));

    // 1. Min EV Filter (strictly uniform on evRoi)
    const passesEv = evRoi >= minEvThreshold;

    // 2. Min Model Probability Filter
    const passesProb = modelP >= minProbNum;

    // 3. Dynamic League Selection Filter (Unicode NFKD diacritic-agnostic)
    const normActiveLeague = normalizeLeagueText(activeLeague);
    const normEdgeLeague = normalizeLeagueText(e.league || e.competition || '');
    const passesLeague = (
      normActiveLeague === 'all' ||
      !normActiveLeague ||
      normEdgeLeague === normActiveLeague
    );

    // 4. Bookmaker Filter
    const edgeBook = (e.bookmaker || '').trim();
    const passesBook = (
      activeBookmaker === 'all' ||
      activeBookmaker === 'ALL' ||
      !activeBookmaker ||
      edgeBook.toUpperCase() === activeBookmaker.toUpperCase()
    );

    return passesEv && passesProb && passesLeague && passesBook;
  }).sort((a, b) => {
    const roiB = typeof b.evRoi === 'number' ? b.evRoi : (typeof b.ev_roi === 'number' ? b.ev_roi : ((b.raw_edge || 0) * 100));
    const roiA = typeof a.evRoi === 'number' ? a.evRoi : (typeof a.ev_roi === 'number' ? a.ev_roi : ((a.raw_edge || 0) * 100));
    return roiB - roiA;
  });

  return `
    <div class="value-scanner-view">
      <!-- Analytical Scope Banner -->
      <div class="explainer-banner" style="border-color: rgba(0, 240, 255, 0.3); background: rgba(0, 240, 255, 0.03);">
        <div class="explainer-content">
          <div class="explainer-title" style="color: var(--accent-cyan);">
            <span>🔬</span>
            <span>APE QUANT +EV VALUE & KELLY STAKE SCANNER (v2.0)</span>
          </div>
          <div class="explainer-text">
            Piyasa marjı Shin yöntemiyle arındırılmış adil oranlar ile Dixon-Coles/Poisson modellerimizin beklenen değer sapmalarını (+EV) listeler. Kasa yönetimi Half-Kelly (0.5x) kriteriyle sınırlandırılmıştır.
          </div>
        </div>
        <div class="banner-tags">
          <span class="badge badge-emerald">SHIN DEVIGGING</span>
          <span class="badge badge-cyan">HALF-KELLY (0.5x)</span>
          <span class="badge badge-amber">SPEC-0012 VERIFIED</span>
        </div>
      </div>

      <!-- Filters -->
      <div class="filter-bar">
        <!-- 1. Min EV Filter Control -->
        <div class="filter-group">
          <span class="filter-label">Min EV (Beklenen Değer):</span>
          <select class="filter-select" id="min-ev-filter">
            <option value="all" ${minEvSelectedStr === 'all' ? 'selected' : ''}>Tüm Fırsatlar (Tüm Bülten)</option>
            <option value="0.0" ${minEvSelectedStr === '0.0' ? 'selected' : ''}>Tüm Pozitif EV (≥ 0.0%)</option>
            <option value="2.0" ${minEvSelectedStr === '2.0' ? 'selected' : ''}>🛡️ Konservatif Değer (EV ≥ +2.0%)</option>
            <option value="3.0" ${minEvSelectedStr === '3.0' ? 'selected' : ''}>🔥 VIP Standart (EV ≥ +3.0%)</option>
            <option value="5.0" ${minEvSelectedStr === '5.0' ? 'selected' : ''}>⚡ Yüksek Değer (EV ≥ +5.0%)</option>
            <option value="8.0" ${minEvSelectedStr === '8.0' ? 'selected' : ''}>💎 Balina Fırsatı (EV ≥ +8.0%)</option>
            <option value="-10.0" ${minEvSelectedStr === '-10.0' ? 'selected' : ''}>Negatifler Dahil (EV ≥ -10.0%)</option>
          </select>
        </div>

        <!-- 2. Dynamic League Selection Filter Control -->
        <div class="filter-group">
          <span class="filter-label">Lig Filtresi:</span>
          <select class="filter-select" id="league-filter">
            <option value="all" ${normalizeLeagueText(activeLeague) === 'all' || !normalizeLeagueText(activeLeague) ? 'selected' : ''}>Tüm Ligler (${availableLeagues.length} Aktif Lig)</option>
            ${availableLeagues.map(lg => `
              <option value="${lg}" ${normalizeLeagueText(activeLeague) === normalizeLeagueText(lg) ? 'selected' : ''}>${lg}</option>
            `).join('')}
          </select>
        </div>

        <!-- 3. Min Model Probability Filter -->
        <div class="filter-group">
          <span class="filter-label">Min Model Olasılığı:</span>
          <select class="filter-select" id="prob-filter">
            <option value="0.0" ${minProbNum === 0.0 ? 'selected' : ''}>Tüm Olasılıklar</option>
            <option value="0.30" ${minProbNum === 0.30 ? 'selected' : ''}>Model Olasılığı ≥ %30</option>
            <option value="0.50" ${minProbNum === 0.50 ? 'selected' : ''}>Model Olasılığı ≥ %50</option>
          </select>
        </div>

        <!-- 4. Bookmaker Filter -->
        <div class="filter-group">
          <span class="filter-label">Büro Filtresi:</span>
          <select class="filter-select" id="book-filter">
            <option value="all" ${activeBookmaker.toLowerCase() === 'all' ? 'selected' : ''}>Tüm Bürolar (Nesine, Pinnacle, Bovada)</option>
            <option value="NESINE" ${activeBookmaker.toUpperCase() === 'NESINE' ? 'selected' : ''}>Nesine (Canlı Bülten)</option>
            <option value="Pinnacle" ${activeBookmaker.toUpperCase() === 'PINNACLE' ? 'selected' : ''}>Pinnacle (Keskin Büro)</option>
            <option value="Bovada" ${activeBookmaker.toUpperCase() === 'BOVADA' ? 'selected' : ''}>Bovada</option>
          </select>
        </div>

        <!-- 5. Commercial SaaS Tier Filter -->
        <div class="filter-group">
          <span class="filter-label">SaaS Abonelik Katmanı:</span>
          <select class="filter-select" id="tier-filter">
            <option value="all" ${(state?.selectedTier || 'all') === 'all' ? 'selected' : ''}>Tüm Katmanlar (Free + Pro + VIP)</option>
            <option value="TIER_1_FREE" ${state?.selectedTier === 'TIER_1_FREE' ? 'selected' : ''}>🥉 Tier 1: Free ($0/Ay — İlk 3 Sinyal)</option>
            <option value="TIER_2_PRO" ${state?.selectedTier === 'TIER_2_PRO' ? 'selected' : ''}>🥈 Tier 2: Pro ($49/Ay — EV ≥ +3.0%)</option>
            <option value="TIER_3_VIP" ${state?.selectedTier === 'TIER_3_VIP' ? 'selected' : ''}>🥇 Tier 3: Syndicate VIP ($299/Ay — EV ≥ +5.0%)</option>
          </select>
        </div>
      </div>

      <!-- Edge Table -->
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">⚡ Değer Sinyalleri & Discrepancy Radar</span>
          <span class="badge badge-emerald">${filtered.length} FIRSAT TESPİT EDİLDİ</span>
        </div>
        <div class="table-responsive">
          <table class="terminal-table">
            <thead>
              <tr>
                <th>Fikstür</th>
                <th>Lig</th>
                <th>Başlama (TRT)</th>
                <th>Piyasa</th>
                <th>Seçim</th>
                <th>Büro</th>
                <th>Oran</th>
                <th>Adil (Shin)</th>
                <th>Vig %</th>
                <th>EV ROI %</th>
                <th>Half-Kelly Kasa</th>
                <th>Aksiyon</th>
              </tr>
            </thead>
            <tbody>
              ${filtered.length === 0 ? `
                <tr>
                  <td colspan="12" style="text-align: center; padding: 3rem; color: var(--text-muted);">
                    <div style="font-family: var(--font-mono); font-size: 0.9rem;">SEÇİLEN FİLTREYE UYGUN SİNYAL BULUNAMADI</div>
                    <div style="font-size: 0.78rem; margin-top: 0.3rem;">Kriterleri genişleterek tekrar kontrol edebilirsiniz.</div>
                  </td>
                </tr>
              ` : ''}
              ${filtered.map(e => `
                <tr style="cursor: pointer;" data-fixture="${e.fixtureId || ''}">
                  <td><strong>${e.homeTeam || 'Unknown'}</strong> vs ${e.awayTeam || 'Unknown'}</td>
                  <td><span class="badge badge-slate" style="font-size: 0.72rem;">${e.league || e.competition || 'Diğer'}</span></td>
                  <td class="mono-num" style="font-size: 0.76rem; color: var(--text-secondary);">${e.kickoffTrt || 'TBD'}</td>
                  <td><span class="badge badge-slate">${e.market || '1X2'}</span></td>
                  <td><strong>${e.selection_display || e.selection || 'N/A'}</strong></td>
                  <td><span class="badge ${e.bookmaker === 'NESINE' ? 'badge-amber' : 'badge-slate'}">${e.bookmaker || 'N/A'}</span></td>
                  <td class="mono-num" style="font-weight: 700; color: var(--text-bright);">${formatOdds(e.entry_odds)}</td>
                  <td class="mono-num" style="color: var(--accent-violet);">${formatOdds(e.fairOddsShin || e.market_fair_odds)}</td>
                  <td class="mono-num" style="font-size: 0.78rem; color: var(--text-muted);">${formatVig(e.shinMargin)}</td>
                  <td>
                    <span class="badge ${e.evRoi >= 6.0 ? 'badge-emerald' : (e.evRoi >= 3.0 ? 'badge-cyan' : (e.evRoi > 0 ? 'badge-amber' : 'badge-rose'))}" style="font-weight: 700;">
                      ${formatEvRoi(e.evRoi)}
                    </span>
                  </td>
                  <td class="mono-num" style="color: ${e.halfKelly > 0 ? 'var(--accent-emerald)' : 'var(--text-muted)'}; font-weight: 600;">
                    ${formatKellyStake(e.halfKelly, state?.userBankroll || 10000)}
                  </td>
                  <td>
                    <div style="display: flex; gap: 0.35rem;">
                      <button class="btn btn-outline btn-copy-signal" style="padding: 0.25rem 0.5rem; font-size: 0.72rem;" title="VIP Telegram formatında kopyala" data-sig-json='${JSON.stringify({
                        home: e.homeTeam || '',
                        away: e.awayTeam || '',
                        league: e.league || e.competition || '',
                        selection: e.selection_display || e.selection || '',
                        book: e.bookmaker || '',
                        odds: e.entry_odds,
                        fair: e.fairOddsShin || e.market_fair_odds,
                        ev: e.evRoi,
                        kelly: e.halfKelly,
                        time: e.kickoffTrt || 'TBD'
                      }).replace(/'/g, "&apos;")}'>
                        📋 Kopyala
                      </button>
                      <button class="btn btn-outline" style="padding: 0.25rem 0.5rem; font-size: 0.72rem;" data-fixture="${e.fixtureId || ''}">
                        İncele →
                      </button>
                    </div>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;
}
