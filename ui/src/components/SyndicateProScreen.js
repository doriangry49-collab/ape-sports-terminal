/**
 * Screen 7: Commercial SaaS Syndicate Pro (Tier 1/2/3, In-Play Sniper, Copula SGP & CLV Alpha)
 */

import { formatOdds, formatPercent } from '../data/normalizer.js';

export function renderSyndicatePro(state, selectedTier = 'all') {
  const syn = state.syndicatePro || {};
  const sniperAlerts = syn.in_play_sniper_alerts || [];
  const sgpCombos = syn.copula_sgp_combinations || [];
  const clv = syn.clv_alpha_summary || {};
  const activeTier = selectedTier || state.selectedTier || 'all';

  const visibleSnipers = activeTier === 'TIER_1_FREE' ? sniperAlerts.slice(0, 1) : sniperAlerts;
  const visibleSgps = activeTier === 'TIER_1_FREE' ? [] : (activeTier === 'TIER_2_PRO' ? sgpCombos.slice(0, 2) : sgpCombos);

  return `
    <div class="syndicate-pro-view">
      <!-- SaaS Commercial Tier Header Banner -->
      <div class="explainer-banner" style="border-color: rgba(16, 185, 129, 0.45); background: linear-gradient(90deg, rgba(16, 185, 129, 0.08), rgba(6, 182, 212, 0.06)); margin-bottom: 1.5rem;">
        <div class="explainer-content">
          <div class="explainer-title" style="color: var(--accent-emerald);">
            <span>🏛️</span>
            <span>APE QUANT SPORTS INTELLIGENCE — COMMERCIAL SAAS & SYNDICATE TERMINAL</span>
          </div>
          <div class="explainer-text">
            30.316 geçmiş maçlık (2021–2026) walk-forward denetimiyle doğrulanmış 5 SOTA kantitatif motor: In-Play Continuous Sniper (10'-40' baskı anomalisi), Clayton/Gumbel Copula SGP, CLV Alpha Attribution ve Kovaryans Duyarlı Portföy Kelly.
          </div>
        </div>
        <div class="banner-tags">
          <span class="badge badge-slate">TIER 1: FREE ($0)</span>
          <span class="badge badge-cyan">TIER 2: PRO ($49/ay)</span>
          <span class="badge badge-emerald">TIER 3: SYNDICATE VIP ($299/ay)</span>
        </div>
      </div>

      <!-- 3-Tier Commercial SaaS Pricing & Access Selector Cards -->
      <div class="grid-4" style="grid-template-columns: repeat(3, 1fr); margin-bottom: 1.5rem;">
        <div class="kpi-card ${activeTier === 'TIER_1_FREE' ? 'cyan' : ''}" style="cursor: pointer;" data-tier-select="TIER_1_FREE">
          <span class="kpi-label">🥉 TIER 1 — FREEMIUM RADAR</span>
          <span class="kpi-value">$0 <small style="font-size: 0.85rem; color: var(--text-muted);">/ Ay</small></span>
          <span class="kpi-sub">Günlük 3 Temel +EV Sinyali • 1X2 Poisson Dağılımı • 1 Canlı Pusu Önizlemesi</span>
        </div>
        <div class="kpi-card ${activeTier === 'TIER_2_PRO' ? 'emerald' : 'cyan'}" style="cursor: pointer;" data-tier-select="TIER_2_PRO">
          <span class="kpi-label">🥈 TIER 2 — PRO TRADER</span>
          <span class="kpi-value">$49 <small style="font-size: 0.85rem; color: var(--text-muted);">/ Ay (1.490 TL)</small></span>
          <span class="kpi-sub">Sıfır Gecikmeli Telegram Push • Tam In-Play Sniper (10'-40') • İY-X / MS-1 Geri Dönüş Radarı</span>
        </div>
        <div class="kpi-card ${activeTier === 'TIER_3_VIP' || activeTier === 'all' ? 'amber' : 'violet'}" style="cursor: pointer;" data-tier-select="TIER_3_VIP">
          <span class="kpi-label">🥇 TIER 3 — SYNDICATE VIP & API</span>
          <span class="kpi-value">$299 <small style="font-size: 0.85rem; color: var(--text-muted);">/ Ay + B2B API</small></span>
          <span class="kpi-sub">Copula SGP Kombinasyon Motoru • CLV Alfa Raporu • Kovaryans Portföy Kelly • REST API</span>
        </div>
      </div>

      <!-- Two Columns: In-Play Continuous Sniper Cards & Copula SGP Panel -->
      <div class="grid-2" style="margin-bottom: 1.5rem;">
        <!-- Column 1: In-Play Continuous Sniper (Live Ambush Cards) -->
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">⚡ In-Play Continuous Sniper (Canlı Pusu Kartları)</span>
            <span class="badge badge-cyan">${visibleSnipers.length} AKTİF PUSU</span>
          </div>
          <div style="display: flex; flex-direction: column; gap: 0.75rem;">
            ${visibleSnipers.length === 0 ? `<div style="padding: 1.5rem; text-align: center; color: var(--text-muted);">Aktif canlı pusu kartı bulunmuyor.</div>` : ''}
            ${visibleSnipers.map(s => `
              <div style="background: rgba(6, 182, 212, 0.06); border: 1px solid rgba(6, 182, 212, 0.3); border-radius: var(--radius-sm); padding: 0.9rem 1rem; cursor: pointer;" data-fixture="${s.fixture_id || ''}">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem;">
                  <strong style="color: var(--text-bright); font-size: 0.95rem;">⚽ ${s.home_team} vs ${s.away_team}</strong>
                  <span class="badge badge-emerald">ROI: +${s.expected_live_roi}%</span>
                </div>
                <div style="font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 0.45rem;">
                  <span>🏆 ${s.league}</span> • <span>⏰ ${s.kickoff_trt}</span> • <span style="color: var(--accent-cyan);">${s.trigger_window}</span>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; font-family: var(--font-mono); font-size: 0.78rem;">
                  <span>🎯 Hedef: <strong>${s.target_market}</strong></span>
                  <span>λ=${s.prematch_lambda} | Hedef Oran: <strong>${formatOdds(s.target_live_odds)}</strong></span>
                </div>
              </div>
            `).join('')}
            ${activeTier === 'TIER_1_FREE' ? `
              <div style="padding: 0.8rem; border: 1px dashed var(--accent-amber); border-radius: var(--radius-sm); text-align: center; font-size: 0.8rem; color: var(--accent-amber);">
                🔒 Tier 1 (Free) modunda yalnızca 1 canlı pusu kartı gösterilir. Tüm canlı pusular için <strong>Tier 2 Pro</strong> katmanına geçin.
                <div style="margin-top: 0.5rem;">
                  <button class="btn-upgrade-trigger" data-trigger-upgrade="403" style="background: var(--accent-amber); color: #000; border: none; padding: 0.3rem 0.8rem; border-radius: var(--radius-sm); font-size: 0.75rem; font-weight: 600; cursor: pointer;">Upgrade to Syndicate PRO</button>
                </div>
              </div>
            ` : ''}
          </div>
        </div>

        <!-- Column 2: Copula SGP Combination Engine -->
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">🧬 Copula SGP Kombinasyon Paneli (Clayton & Gumbel)</span>
            <span class="badge badge-amber">${visibleSgps.length} SGP KOMBİNASYONU</span>
          </div>
          <div style="display: flex; flex-direction: column; gap: 0.75rem;">
            ${visibleSgps.length === 0 ? `
              <div style="padding: 1.5rem; border: 1px dashed var(--accent-amber); border-radius: var(--radius-sm); text-align: center; color: var(--accent-amber);">
                🔒 Copula SGP Kombinasyon Motoru <strong>Tier 3 Syndicate VIP</strong> abonelerine özeldir. Üstteki karttan Tier 3 VIP seçerek kilidi açabilirsiniz.
                <div style="margin-top: 0.75rem;">
                  <button class="btn-upgrade-trigger" data-trigger-upgrade="403" style="background: linear-gradient(135deg, var(--accent-cyan), var(--accent-emerald)); color: #000; border: none; padding: 0.4rem 1rem; border-radius: var(--radius-sm); font-size: 0.8rem; font-weight: 600; cursor: pointer;">Upgrade to Syndicate PRO</button>
                </div>
              </div>
            ` : ''}
            ${visibleSgps.map(g => `
              <div style="background: rgba(245, 158, 11, 0.06); border: 1px solid rgba(245, 158, 11, 0.35); border-radius: var(--radius-sm); padding: 0.9rem 1rem; cursor: pointer;" data-fixture="${g.fixture_id || ''}">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.35rem;">
                  <strong style="color: var(--text-bright); font-size: 0.95rem;">🔥 ${g.home_team} vs ${g.away_team}</strong>
                  <span class="badge badge-emerald">SGP EV: +${g.joint_ev_roi}%</span>
                </div>
                <div style="font-size: 0.8rem; color: var(--accent-amber); margin-bottom: 0.4rem;">
                  🔗 <strong>Ayak 1:</strong> ${g.leg_1} + <strong>Ayak 2:</strong> ${g.leg_2}
                </div>
                <div style="display: flex; justify-content: space-between; font-family: var(--font-mono); font-size: 0.76rem; color: var(--text-secondary);">
                  <span>Model: ${g.copula_family}</span>
                  <span>Birleşik Olasılık: ${formatPercent(g.joint_prob)}</span>
                  <span>Adil: ${formatOdds(g.fair_joint_odds)} | Büro: <strong style="color: var(--text-bright);">${formatOdds(g.book_sgp_odds)}</strong></span>
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      </div>

      <!-- CLV Alpha Attribution & 30k Historical Strategy Verification -->
      <div class="panel" style="margin-bottom: 1.5rem;">
        <div class="panel-header">
          <span class="panel-title">📈 CLV Alpha Attribution & 30.316 Maçlık Doğrulanmış Taktik Matrisi</span>
          <span class="badge badge-emerald">ZERO-LEAKAGE WALK-FORWARD</span>
        </div>
        <div class="grid-4" style="margin-bottom: 1rem;">
          <div style="background: rgba(0,0,0,0.25); padding: 0.8rem 1rem; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.75rem; color: var(--text-muted);">ALFA-01: İY 0.5 ÜST TEMPO</div>
            <div style="font-family: var(--font-mono); font-size: 1.15rem; font-weight: 700; color: var(--accent-emerald);">%76.9 WR (+3.8% ROI)</div>
            <div style="font-size: 0.72rem; color: var(--text-secondary);">7.584 Maç Doğrulandı</div>
          </div>
          <div style="background: rgba(0,0,0,0.25); padding: 0.8rem 1rem; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.75rem; color: var(--text-muted);">ALFA-02: İY-X / MS-1 PUSU</div>
            <div style="font-family: var(--font-mono); font-size: 1.15rem; font-weight: 700; color: var(--accent-cyan);">%57.5 WR (+15.2% Canlı)</div>
            <div style="font-size: 0.72rem; color: var(--text-secondary);">1.194 Ağır Favori Maçı</div>
          </div>
          <div style="background: rgba(0,0,0,0.25); padding: 0.8rem 1rem; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.75rem; color: var(--text-muted);">ALFA-04: 3D KORNER 8.5 ÜST</div>
            <div style="font-family: var(--font-mono); font-size: 1.15rem; font-weight: 700; color: var(--accent-emerald);">%73.1 WR (+13.3% ROI)</div>
            <div style="font-size: 0.72rem; color: var(--text-secondary);">10 Aylık Walk-Forward Omurgası</div>
          </div>
          <div style="background: rgba(0,0,0,0.25); padding: 0.8rem 1rem; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.75rem; color: var(--text-muted);">CLV ALFA AYRIŞTIRMASI</div>
            <div style="font-family: var(--font-mono); font-size: 1.15rem; font-weight: 700; color: var(--accent-amber);">%${clv.stale_alpha_contribution_pct ?? 65} Stale / %${clv.info_alpha_contribution_pct ?? 35} Info</div>
            <div style="font-size: 0.72rem; color: var(--text-secondary);">Pinnacle Kapanış Referanslı</div>
          </div>
        </div>
      </div>

      <!-- Faz 4: Institutional Multivariate Portfolio Kelly Allocator & Sepet Simülatörü -->
      <div class="panel" style="border-color: rgba(6, 182, 212, 0.35);">
        <div class="panel-header">
          <span class="panel-title">🧮 Faz 4: Çok Değişkenli Kovaryans Portföy Kelly Simülatörü</span>
          <span class="badge badge-cyan">GROSSMAN-ZHOU BOUNDED (MAX 35% RISK)</span>
        </div>
        <div style="padding: 0.5rem 0 1rem 0; font-size: 0.85rem; color: var(--text-secondary); line-height: 1.5;">
          Aynı bülten sepetine birden fazla maç eklendiğinde bağımsız bahisler kasayı eritme riski (drawdown) doğurur. Kovaryans Matrisi ($V$) ve Çeyrek-Kelly ($0.25x$) algoritması, maçların birbirleriyle olan bağımlılığını hesaba katarak en yüksek sermaye büyüme oranını ($g^*$) sağlayan güvenli TL bahis tutarını belirler (SPEC-0015 Asgari 50 TL kuralı uygulanır).
        </div>

        <div class="grid-4" style="margin-bottom: 1.25rem;">
          <div style="background: rgba(0,0,0,0.2); padding: 0.8rem 1rem; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.75rem; color: var(--text-muted);">KULLANICI KASASI (BANKROLL)</div>
            <div style="font-family: var(--font-mono); font-size: 1.25rem; font-weight: 700; color: var(--accent-cyan); margin-top: 0.2rem;">
              ${(state.userBankroll || 10000).toLocaleString('tr-TR')} TL
            </div>
            <div style="font-size: 0.72rem; color: var(--text-muted);">Kasa Yönetimi Aktif</div>
          </div>
          <div style="background: rgba(0,0,0,0.2); padding: 0.8rem 1rem; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.75rem; color: var(--text-muted);">FRAKSİYONEL KELLY KATSAYISI</div>
            <div style="font-family: var(--font-mono); font-size: 1.25rem; font-weight: 700; color: var(--accent-emerald); margin-top: 0.2rem;">
              0.25x (Quarter-Kelly)
            </div>
            <div style="font-size: 0.72rem; color: var(--text-muted);">Varyans Sönümleme Kalkanı</div>
          </div>
          <div style="background: rgba(0,0,0,0.2); padding: 0.8rem 1rem; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.75rem; color: var(--text-muted);">MAKSİMUM PORTFÖY RİSKİ</div>
            <div style="font-family: var(--font-mono); font-size: 1.25rem; font-weight: 700; color: var(--accent-amber); margin-top: 0.2rem;">
              %35.0 (~${Math.round((state.userBankroll || 10000) * 0.35).toLocaleString('tr-TR')} TL)
            </div>
            <div style="font-size: 0.72rem; color: var(--text-muted);">Grossman-Zhou Tavanı</div>
          </div>
          <div style="background: rgba(0,0,0,0.2); padding: 0.8rem 1rem; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.75rem; color: var(--text-muted);">ASGARİ KUPON ŞARTI</div>
            <div style="font-family: var(--font-mono); font-size: 1.25rem; font-weight: 700; color: var(--text-bright); margin-top: 0.2rem;">
              ≥ 50.00 TL (SPEC-0015)
            </div>
            <div style="font-size: 0.72rem; color: var(--accent-emerald);">Kanun Kuralı Korumalı</div>
          </div>
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 0.75rem;">
          <button id="btn-run-portfolio-opt" class="btn btn-primary" style="background: linear-gradient(135deg, var(--accent-cyan), var(--accent-emerald)); border: none; color: #000; font-weight: 700; padding: 0.55rem 1.25rem; border-radius: var(--radius-sm); cursor: pointer;">
            ⚡ Aktif Sinyaller İçin Kovaryans Portföy Kelly Hesapla
          </button>
        </div>

        <div id="portfolio-opt-result" style="margin-top: 1rem; display: none;"></div>
      </div>
    </div>
  `;
}

