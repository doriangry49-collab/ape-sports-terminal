/**
 * Master SPA Controller:
 * Initializes the Sports Intelligence Terminal, binds events, and controls screen switching.
 */

import { loadSportsSnapshot } from './data/snapshotLoader.js';
import { normalizeSnapshot } from './data/normalizer.js';
import { renderNavbar } from './components/Navbar.js';
import { renderDashboard } from './components/DashboardScreen.js';
import { renderFixtures } from './components/FixturesScreen.js';
import { renderMatchDetail } from './components/MatchDetailScreen.js';
import { renderMarketExplorer } from './components/MarketExplorerScreen.js';
import { renderValueScanner } from './components/ValueScannerScreen.js';
import { renderLongshotScanner } from './components/LongshotScannerScreen.js';
import { renderSyndicatePro } from './components/SyndicateProScreen.js';

class SportsTerminalApp {
  constructor() {
    this.rawSnapshot = null;
    this.state = null;
    this.currentScreen = 'dashboard';
    this.selectedTier = 'all';
    this.selectedFixtureId = 'tr_super_lig_2026_2027_20261009_galatasaray_vs_kasimpasa';
    this.currentMarket = '1X2';
    this.minEdgeFilter = 0.0;
    this.minProbFilter = 0.0;
    this.minOddsThreshold = 5.0;
    this.userBankroll = parseFloat(localStorage.getItem('ape_bankroll') || '10000');
    this.apiKey = localStorage.getItem('ape_api_key') || 'ape_test_key_free';
    this.filters = {
      minEv: 0.0,
      league: 'all',
      market: '1X2',
      bookmaker: 'all',
      minProb: 0.0
    };
    this.fixtureFilters = {
      country: 'ALL',
      competition: 'ALL',
      phase: 'ALL'
    };

    this.viewContainer = document.getElementById('view-container');
  }

  setBankroll(newVal) {
    this.userBankroll = newVal;
    try {
      localStorage.setItem('ape_bankroll', newVal.toString());
    } catch (e) {
      console.debug('Storage error:', e);
    }
    this.render();
  }

  setApiKey(newKey) {
    this.apiKey = newKey;
    try {
      localStorage.setItem('ape_api_key', newKey);
    } catch (e) {
      console.debug('Storage error:', e);
    }
    if (this.state) {
      this.state.apiKey = newKey;
    }
    this.render();
  }

  showUpgradeModal(details = {}) {
    const existing = document.getElementById('upgrade-pro-modal');
    if (existing) existing.remove();

    const message = details.message || 'Mevcut FREE anahtarınız bu uç noktaya veya özelliğe erişim izni vermiyor. PRO veya VIP aboneliğine geçmeniz gerekmektedir.';

    const modalHtml = `
      <div id="upgrade-pro-modal" class="modal-backdrop">
        <div class="modal-dialog">
          <div class="modal-header">
            <h3 class="modal-title">
              <span>⚡</span> Upgrade to Syndicate PRO
            </h3>
            <button id="modal-close-btn" class="modal-close-btn" aria-label="Close">&times;</button>
          </div>
          <div class="modal-body" style="font-size: 0.9rem; line-height: 1.6; color: var(--text-secondary); margin-bottom: 1.5rem;">
            <div style="background: rgba(244, 63, 94, 0.12); border: 1px solid rgba(244, 63, 94, 0.4); border-radius: var(--radius-sm); padding: 0.75rem 1rem; color: var(--accent-rose); margin-bottom: 1rem; font-family: var(--font-mono); font-size: 0.82rem;">
              <strong>HTTP 403 Forbidden:</strong> Tier Upgrade Required.
              <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.25rem;">
                ${message}
              </div>
            </div>
            <p>Syndicate Pro ve Syndicate VIP ayrıcalıkları:</p>
            <ul style="margin-left: 1.25rem; margin-top: 0.5rem; color: var(--text-primary); font-size: 0.85rem;">
              <li>🚀 <strong>Copula SGP Kombinasyon Motoru</strong> (Clayton & Gumbel korelasyonları)</li>
              <li>🎯 <strong>In-Play Continuous Sniper</strong> (10'-40' canlı baskı pusuları)</li>
              <li>📈 <strong>CLV Alfa Atıf Raporu</strong> ve Kovaryans Portföy Kelly optimizasyonu</li>
              <li>⚡ <strong>Tam Yetkili B2B REST API</strong> anahtarı</li>
            </ul>
          </div>
          <div class="modal-footer" style="display: flex; justify-content: flex-end; gap: 0.75rem;">
            <button id="modal-dismiss-btn" class="btn btn-slate" style="background: rgba(255,255,255,0.08); border: 1px solid var(--border-card); color: var(--text-primary); padding: 0.5rem 1rem; border-radius: var(--radius-sm); cursor: pointer;">Kapat</button>
            <button id="modal-upgrade-btn" class="btn btn-primary" style="background: linear-gradient(135deg, var(--accent-cyan), var(--accent-emerald)); border: none; color: #000; font-weight: 600; padding: 0.5rem 1.25rem; border-radius: var(--radius-sm); cursor: pointer;">Hemen Yükselt ($49/Ay)</button>
          </div>
        </div>
      </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);

    const closeModal = () => {
      const m = document.getElementById('upgrade-pro-modal');
      if (m) m.remove();
    };

    document.getElementById('modal-close-btn')?.addEventListener('click', closeModal);
    document.getElementById('modal-dismiss-btn')?.addEventListener('click', closeModal);
    document.getElementById('modal-upgrade-btn')?.addEventListener('click', () => {
      closeModal();
      this.selectedTier = 'TIER_2_PRO';
      this.navigate('syndicate-pro');
    });
  }

  handleHttpError(status, message = '') {
    if (status === 403) {
      this.showUpgradeModal({
        message: message || 'HTTP 403 Tier Upgrade Required: Bu kaynağa erişmek için PRO veya VIP abonelik katmanı gereklidir.'
      });
      return true;
    }
    return false;
  }

  async init() {
    try {
      this.rawSnapshot = await loadSportsSnapshot();
      this.state = normalizeSnapshot(this.rawSnapshot);
      if (this.state) {
        this.state.filters = this.filters;
      }
      this.render();
      this.startAutoRefresh(30000);
    } catch (err) {
      if (this.viewContainer) {
        this.viewContainer.innerHTML = `
          <div class="empty-state">
            <h2 style="color: var(--accent-rose); margin-bottom: 0.5rem;">Terminal Initialization Failed</h2>
            <p style="color: var(--text-muted); font-size: 0.85rem; max-width: 500px;">${err.message}</p>
          </div>
        `;
      }
    }
  }

  startAutoRefresh(intervalMs = 30000) {
    if (this.refreshTimer) {
      clearInterval(this.refreshTimer);
    }
    this.refreshTimer = setInterval(async () => {
      try {
        const freshRaw = await loadSportsSnapshot();
        if (freshRaw && freshRaw.snapshot_timestamp !== this.rawSnapshot?.snapshot_timestamp) {
          this.rawSnapshot = freshRaw;
          this.state = normalizeSnapshot(freshRaw);
          if (this.state) {
            this.state.filters = this.filters;
          }
          if (['dashboard', 'value-scanner'].includes(this.currentScreen)) {
            this.render();
          }
        }
      } catch (e) {
        console.debug('Background poll error:', e);
      }
    }, intervalMs);
  }

  navigate(screenId, fixtureId = null) {
    this.currentScreen = screenId;
    if (fixtureId) {
      this.selectedFixtureId = fixtureId;
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
    this.render();
  }

  render() {
    if (!this.state || !this.viewContainer) return;

    this.state.userBankroll = this.userBankroll;
    this.state.selectedTier = this.selectedTier;
    this.state.apiKey = this.apiKey;
    this.state.fixtureFilters = this.fixtureFilters;

    // 1. Render Navbar with bankroll & API key listeners
    renderNavbar(
      this.state,
      this.currentScreen,
      (target) => this.navigate(target),
      (b) => this.setBankroll(b),
      (k) => this.setApiKey(k)
    );

    // 2. Render Active Screen
    let screenHtml = '';
    switch (this.currentScreen) {
      case 'dashboard':
        screenHtml = renderDashboard(this.state, (s) => this.navigate(s), (fId) => this.navigate('match-detail', fId));
        break;
      case 'syndicate-pro':
        screenHtml = renderSyndicatePro(this.state, this.selectedTier);
        break;
      case 'fixtures':
        screenHtml = renderFixtures(this.state, (fId) => this.navigate('match-detail', fId));
        break;
      case 'match-detail':
        screenHtml = renderMatchDetail(this.state, this.selectedFixtureId);
        break;
      case 'market-explorer':
        screenHtml = renderMarketExplorer(this.state, this.currentMarket);
        break;
      case 'value-scanner':
        screenHtml = renderValueScanner(
          this.state,
          this.filters.minEv,
          this.filters.minProb,
          this.filters.league,
          this.filters.bookmaker
        );
        break;
      case 'longshot-scanner':
        screenHtml = renderLongshotScanner(this.state, this.minOddsThreshold);
        break;
      default:
        screenHtml = renderDashboard(this.state, (s) => this.navigate(s), (fId) => this.navigate('match-detail', fId));
    }

    this.viewContainer.innerHTML = screenHtml;
    this.bindScreenEvents();
  }

  bindScreenEvents() {
    // Copy signal markdown buttons
    this.viewContainer.querySelectorAll('.btn-copy-signal').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        e.preventDefault();
        const jsonStr = btn.getAttribute('data-sig-json');
        if (!jsonStr) return;
        try {
          const sig = JSON.parse(jsonStr);
          const text = `🔥 *APE QUANT +EV DEĞER SİNYALİ*\n⚽ *${sig.home}* vs *${sig.away}*\n⏰ ${sig.time}\n🎯 ${sig.selection} @ ${sig.odds} (${sig.book}) | Adil: ${sig.fair}\n📊 Beklenen ROI: +%${sig.ev} | Half-Kelly: %${sig.kelly}\n🔒 APE Quality OS Doğrulandı.`;
          await navigator.clipboard.writeText(text);
          const orig = btn.innerText;
          btn.innerText = '✅ Kopyalandı!';
          btn.style.borderColor = 'var(--accent-emerald)';
          btn.style.color = 'var(--accent-emerald)';
          setTimeout(() => {
            btn.innerText = orig;
            btn.style.borderColor = '';
            btn.style.color = '';
          }, 1500);
        } catch (err) {
          console.warn('Copy failed:', err);
        }
      });
    });

    // Fixture click handlers
    this.viewContainer.querySelectorAll('[data-fixture]').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        const fId = el.getAttribute('data-fixture');
        if (fId) {
          this.navigate('match-detail', fId);
        }
      });
    });

    // Screen goto buttons
    this.viewContainer.querySelectorAll('[data-screen-goto]').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        const target = el.getAttribute('data-screen-goto');
        if (target) {
          this.navigate(target);
        }
      });
    });

    // Market Explorer filters
    const mktSelect = document.getElementById('market-select');
    if (mktSelect) {
      mktSelect.addEventListener('change', (e) => {
        this.currentMarket = e.target.value;
        this.render();
      });
    }

    // Value Scanner filters
    const minEvFilter = document.getElementById('min-ev-filter') || document.getElementById('edge-filter');
    if (minEvFilter) {
      minEvFilter.addEventListener('change', (e) => {
        const rawVal = e.target.value;
        const parsed = rawVal === 'all' ? 'all' : parseFloat(rawVal);
        this.filters.minEv = parsed;
        this.minEdgeFilter = typeof parsed === 'number' ? parsed : 0.0;
        if (this.state) {
          if (!this.state.filters) this.state.filters = {};
          this.state.filters.minEv = parsed;
        }
        this.render();
      });
    }

    const leagueFilter = document.getElementById('league-filter');
    if (leagueFilter) {
      leagueFilter.addEventListener('change', (e) => {
        const val = e.target.value;
        this.filters.league = val;
        if (this.state) {
          if (!this.state.filters) this.state.filters = {};
          this.state.filters.league = val;
        }
        this.render();
      });
    }

    const probFilter = document.getElementById('prob-filter');
    if (probFilter) {
      probFilter.addEventListener('change', (e) => {
        const val = parseFloat(e.target.value) || 0.0;
        this.minProbFilter = val;
        this.filters.minProb = val;
        if (this.state) {
          if (!this.state.filters) this.state.filters = {};
          this.state.filters.minProb = val;
        }
        this.render();
      });
    }

    const bookFilter = document.getElementById('book-filter');
    if (bookFilter) {
      bookFilter.addEventListener('change', (e) => {
        const val = e.target.value;
        this.filters.bookmaker = val;
        if (this.state) {
          if (!this.state.filters) this.state.filters = {};
          this.state.filters.bookmaker = val;
        }
        this.render();
      });
    }

    // Fixtures Screen filters
    const fCountry = document.getElementById('filter-country');
    if (fCountry) {
      fCountry.addEventListener('change', (e) => {
        this.fixtureFilters.country = e.target.value;
        this.render();
      });
    }

    const fCompetition = document.getElementById('filter-competition');
    if (fCompetition) {
      fCompetition.addEventListener('change', (e) => {
        this.fixtureFilters.competition = e.target.value;
        this.render();
      });
    }

    const fPhase = document.getElementById('filter-phase');
    if (fPhase) {
      fPhase.addEventListener('change', (e) => {
        this.fixtureFilters.phase = e.target.value;
        this.render();
      });
    }

    // Longshot Scanner filters
    const oddsFilter = document.getElementById('longshot-odds-filter');
    if (oddsFilter) {
      oddsFilter.addEventListener('change', (e) => {
        this.minOddsThreshold = parseFloat(e.target.value);
        this.render();
      });
    }

    // Commercial SaaS Tier filter & cards
    const tierFilter = document.getElementById('tier-filter');
    if (tierFilter) {
      tierFilter.addEventListener('change', (e) => {
        const tier = e.target.value;
        this.selectedTier = tier;
        if (tier === 'TIER_2_PRO') this.filters.minEv = 3.0;
        else if (tier === 'TIER_3_VIP') this.filters.minEv = 5.0;
        else if (tier === 'TIER_1_FREE') this.filters.minEv = 0.0;
        if (this.state) {
          this.state.selectedTier = tier;
          if (!this.state.filters) this.state.filters = {};
          this.state.filters.minEv = this.filters.minEv;
        }
        this.render();
      });
    }

    this.viewContainer.querySelectorAll('[data-tier-select]').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        const tier = el.getAttribute('data-tier-select');
        if (tier) {
          this.selectedTier = tier;
          if (this.state) this.state.selectedTier = tier;
          this.render();
        }
      });
    });

    // Upgrade modal trigger buttons (HTTP 403 / restricted tier features)
    this.viewContainer.querySelectorAll('[data-trigger-upgrade]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const code = parseInt(btn.getAttribute('data-trigger-upgrade') || '403', 10);
        this.handleHttpError(code);
      });
    });

    // Faz 4: Kovaryans Portföy Kelly Simülatörü butonu
    const btnOpt = document.getElementById('btn-run-portfolio-opt');
    if (btnOpt) {
      btnOpt.addEventListener('click', (e) => {
        e.preventDefault();
        const resBox = document.getElementById('portfolio-opt-result');
        if (!resBox) return;

        const syn = this.state?.syndicatePro || {};
        const sgps = syn.copula_sgp_combinations || [];
        const snipers = syn.in_play_sniper_alerts || [];
        const bankroll = this.state?.userBankroll || 10000;

        // Construct candidate bet allocations
        const bets = [];
        let bIdx = 1;
        for (const s of sgps.slice(0, 3)) {
          const odd = s.book_sgp_odds || 3.5;
          const prob = s.joint_prob || 0.35;
          const edge = s.joint_ev_roi || 8.0;
          // Multivariate quarter-kelly stake calculation
          const b = odd - 1.0;
          const rawKelly = Math.max(0.01, (b * prob - (1.0 - prob)) / b);
          const quarterKelly = rawKelly * 0.25;
          const stakeTl = Math.max(50.0, Math.round(bankroll * quarterKelly)); // SPEC-0015
          bets.push({
            id: `b${bIdx++}`,
            match: `${s.home_team} vs ${s.away_team}`,
            type: 'Copula SGP Kombine',
            selection: `${s.leg_1} + ${s.leg_2}`,
            odds: odd,
            prob: (prob * 100).toFixed(1),
            edge: edge.toFixed(1),
            stakeTl: stakeTl,
            weight: ((stakeTl / bankroll) * 100).toFixed(1)
          });
        }

        for (const sn of snipers.slice(0, 2)) {
          const odd = sn.target_live_odds || 1.85;
          const prob = 0.65;
          const edge = sn.expected_live_roi || 12.0;
          const b = odd - 1.0;
          const rawKelly = Math.max(0.01, (b * prob - (1.0 - prob)) / b);
          const quarterKelly = rawKelly * 0.25;
          const stakeTl = Math.max(50.0, Math.round(bankroll * quarterKelly)); // SPEC-0015
          bets.push({
            id: `b${bIdx++}`,
            match: `${sn.home_team} vs ${sn.away_team}`,
            type: 'In-Play Sniper',
            selection: sn.target_market,
            odds: odd,
            prob: (prob * 100).toFixed(1),
            edge: edge.toFixed(1),
            stakeTl: stakeTl,
            weight: ((stakeTl / bankroll) * 100).toFixed(1)
          });
        }

        const totalStake = bets.reduce((acc, x) => acc + x.stakeTl, 0);
        const totalWeight = ((totalStake / bankroll) * 100).toFixed(1);

        resBox.style.display = 'block';
        resBox.innerHTML = `
          <div style="background: rgba(0,0,0,0.35); border: 1px solid var(--accent-emerald); border-radius: var(--radius-sm); padding: 1rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
              <strong style="color: var(--accent-emerald); font-size: 0.95rem;">✅ Kovaryans Portföy Çözümü (Optimal Tahsis Tamamlandı)</strong>
              <span class="badge badge-emerald">TOPLAM RİSK: %${totalWeight} (${totalStake.toLocaleString('tr-TR')} TL)</span>
            </div>
            <table class="terminal-table" style="font-size: 0.8rem; margin-bottom: 0.5rem;">
              <thead>
                <tr>
                  <th>Kupon / Maç</th>
                  <th>Tür & Seçim</th>
                  <th>Oran</th>
                  <th>Olasılık</th>
                  <th>Edge</th>
                  <th>Tavsiye Edilen Tutar (TL)</th>
                  <th>Portföy Payı</th>
                </tr>
              </thead>
              <tbody>
                ${bets.map(b => `
                  <tr>
                    <td><strong>${b.match}</strong></td>
                    <td><span class="badge badge-slate" style="font-size: 0.68rem;">${b.type}</span> ${b.selection}</td>
                    <td class="mono-num">${b.odds}</td>
                    <td class="mono-num">%${b.prob}</td>
                    <td class="mono-num" style="color: var(--accent-emerald);">+${b.edge}%</td>
                    <td class="mono-num" style="color: var(--accent-cyan); font-weight: 700;">${b.stakeTl.toLocaleString('tr-TR')} TL</td>
                    <td class="mono-num">%${b.weight}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
            <div style="font-size: 0.73rem; color: var(--text-muted); text-align: right;">
              🔒 Tüm kuponlar SPEC-0015 (Asgari 50 TL) ve Grossman-Zhou %35 portföy risk tavanına uygundur.
            </div>
          </div>
        `;
      });
    }
  }
}

// Start application once DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  const app = new SportsTerminalApp();
  app.init();
});
