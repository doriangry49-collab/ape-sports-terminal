"""Fast browser bundle builder without re-scanning thousands of gold predictions."""

import re
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent
SRC_DIR = UI_DIR / "src"

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
    content = re.sub(r"^\s*import\s+[^;]+;\s*$", "", content, flags=re.MULTILINE)
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
