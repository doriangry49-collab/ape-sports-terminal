/**
 * Navbar Component:
 * Terminal Header, Navigation Tabs, and Data Snapshot Integrity Badges.
 */

export function renderNavbar(state, currentScreen, onNavigate, onBankrollChange, onApiKeyChange) {
  const container = document.getElementById('navbar-container');
  if (!container) return;

  const screens = [
    { id: 'dashboard', label: 'Dashboard' },
    { id: 'syndicate-pro', label: '⚡ Syndicate Pro (SaaS)' },
    { id: 'fixtures', label: 'Football Fixtures' },
    { id: 'match-detail', label: 'Match Detail' },
    { id: 'market-explorer', label: 'Market Explorer' },
    { id: 'value-scanner', label: 'Value / Edge Scanner' },
    { id: 'longshot-scanner', label: 'Longshot Scanner' },
  ];

  const navItemsHtml = screens.map(s => `
    <button class="nav-item ${currentScreen === s.id ? 'active' : ''}" data-screen="${s.id}">
      ${s.label}
    </button>
  `).join('');

  container.innerHTML = `
    <nav class="terminal-navbar">
      <div class="brand-section">
        <a href="#" class="brand-logo" data-screen="dashboard">
          <span class="logo-badge">APE</span>
          <span class="brand-title">SPORTS INTELLIGENCE</span>
          <span class="brand-version">${state?.engineVersion || 'v2.0-quant-shin'}</span>
        </a>
      </div>

      <div class="nav-links">
        ${navItemsHtml}
      </div>

      <div class="status-widget">
        <div class="api-key-container" title="APE Engine API Anahtarınız (FREE / PRO / VIP)">
          <span class="api-key-label">🔑 API:</span>
          <input type="text" id="api-key-input" class="api-key-input" placeholder="ape_test_key_..." value="${state?.apiKey || ''}">
        </div>
        <div class="bankroll-container" title="Kelly pozisyon büyüklüğü için aktif kasanız">
          <span class="bankroll-label">KASA:</span>
          <input type="number" id="bankroll-input" class="bankroll-input" value="${state?.userBankroll || 10000}" min="100" step="500">
          <span class="bankroll-cur">TL</span>
        </div>
        <span class="phase-pill ${(state?.matchPhase || 'PREMATCH').toLowerCase()}">${state?.matchPhase || 'PREMATCH'}</span>
        <span class="snapshot-pill">LIVE: ${state?.provider || 'PROP_LINE_AND_NESINE_CDN'}</span>
      </div>
    </nav>
  `;

  // Attach navigation listeners
  container.querySelectorAll('[data-screen]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const target = btn.getAttribute('data-screen');
      onNavigate(target);
    });
  });

  // Attach bankroll input listener
  const bInput = document.getElementById('bankroll-input');
  if (bInput && onBankrollChange) {
    bInput.addEventListener('change', (e) => {
      const val = parseFloat(e.target.value) || 10000;
      onBankrollChange(val);
    });
  }

  // Attach API key input listener
  const kInput = document.getElementById('api-key-input');
  if (kInput && onApiKeyChange) {
    kInput.addEventListener('change', (e) => {
      const val = (e.target.value || '').trim();
      onApiKeyChange(val);
    });
  }
}
