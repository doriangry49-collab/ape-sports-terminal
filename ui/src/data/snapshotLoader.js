/**
 * Snapshot Loader: Reads the static pre-computed Sports Intelligence Snapshot.
 * 
 * Strict Principle:
 * Read-only fetch. Never alters the backend files.
 */

export async function loadSportsSnapshot() {
  try {
    // 1. If preloaded into memory (e.g. file:/// protocol or bundled script), use it immediately!
    if (typeof window !== 'undefined' && window.__SPORTS_SNAPSHOT__) {
      return window.__SPORTS_SNAPSHOT__;
    }

    // 2. Localhost web server fetch
    const response = await fetch(`data/sports_intelligence_snapshot.json?_t=${Date.now()}`);
    if (!response.ok) {
      throw new Error(`Failed to load sports intelligence snapshot: ${response.status} ${response.statusText}`);
    }
    const data = await response.json();
    return data;
  } catch (error) {
    if (typeof window !== 'undefined' && window.__SPORTS_SNAPSHOT__) {
      return window.__SPORTS_SNAPSHOT__;
    }
    console.error('Error loading sports intelligence snapshot:', error);
    throw error;
  }
}
