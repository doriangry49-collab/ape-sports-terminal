"""Build unified browser bundle for Sports Intelligence Terminal UI.

Enables the UI to work 100% out of the box in ANY modern browser:
- Direct file path copy-pasting (file:/// protocol without CORS blocks)
- Localhost web servers (http://localhost:8000/ui)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent
SRC_DIR = UI_DIR / "src"
DATA_DIR = UI_DIR / "data"

# 1. Refresh sports_intelligence_snapshot.json and generate snapshot_data.js
try:
    import sys as _sys
    if str(UI_DIR) not in _sys.path:
        _sys.path.insert(0, str(UI_DIR))
    from export_snapshot import generate_ui_snapshot
    generate_ui_snapshot()
except Exception as _snap_err:
    print(f"Notice: Could not refresh snapshot via export_snapshot: {_snap_err}")

json_snapshot_file = DATA_DIR / "sports_intelligence_snapshot.json"
if json_snapshot_file.exists():
    try:
        data = json.loads(json_snapshot_file.read_text(encoding="utf-8"))
        js_data_file = DATA_DIR / "snapshot_data.js"
        js_content = f"window.__SPORTS_SNAPSHOT__ = {json.dumps(data, ensure_ascii=False)};\n"
        js_data_file.write_text(js_content, encoding="utf-8")
        print(f"Generated {js_data_file} ({len(js_content)} bytes)")
    except Exception as e:
        print(f"Error generating snapshot_data.js: {e}")

# 2. Files to bundle in topological dependency order
bundle_order = [
    SRC_DIR / "data" / "normalizer.js",
    SRC_DIR / "data" / "selectors.js",
    SRC_DIR / "data" / "snapshotLoader.js",
    SRC_DIR / "components" / "Navbar.js",
    SRC_DIR / "components" / "DashboardScreen.js",
    SRC_DIR / "components" / "FixturesScreen.js",
    SRC_DIR / "components" / "MatchDetailScreen.js",
    SRC_DIR / "components" / "MarketExplorerScreen.js",
    SRC_DIR / "components" / "ValueScannerScreen.js",
    SRC_DIR / "components" / "LongshotScannerScreen.js",
    SRC_DIR / "components" / "SyndicateProScreen.js",
    SRC_DIR / "app.js",
]

bundled_code = [
    "/**",
    " * APE Sports Intelligence Terminal - Unified Production Bundle",
    " * Supports both file:/// (zero CORS) and http://localhost:8000/ environments.",
    " */",
    "(function() {",
    "  'use strict';",
]

for file_path in bundle_order:
    if not file_path.exists():
        print(f"Warning: {file_path} not found")
        continue

    content = file_path.read_text(encoding="utf-8")

    # Strip ES module import lines (e.g. import ... from '...';)
    content = re.sub(r"^\s*import\s+[^;]+;\s*$", "", content, flags=re.MULTILINE)
    # Strip export keywords (e.g. export function -> function, export async function -> async function)
    content = re.sub(r"^\s*export\s+default\s+", "", content, flags=re.MULTILINE)
    content = re.sub(
        r"^\s*export\s+((?:async\s+)?(?:function|class|const|let|var))\s+",
        r"\1 ",
        content,
        flags=re.MULTILINE,
    )

    bundled_code.append(f"\n// ==================== {file_path.name} ====================")
    bundled_code.append(content)

bundled_code.append("\n})();")

bundle_file = UI_DIR / "bundle.js"
bundle_file.write_text("\n".join(bundled_code), encoding="utf-8")
print(f"Successfully created {bundle_file} ({bundle_file.stat().st_size} bytes)")
