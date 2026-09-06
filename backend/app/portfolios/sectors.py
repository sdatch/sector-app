"""Short, stable per-sector codes. Manual (no-CSV) portfolios store one
pseudo-position per sector using these as the position ticker (ticker is
String(16); full GICS names exceed that). The `sector` column carries the real
name, so allocation resolution reads sector directly."""

from __future__ import annotations

# Sentinel stored in Position.sector for a pooled vehicle. A fund holds many
# sectors, so it has no single one; the real breakdown lives in the snapshot's
# fund_composition table and is applied at evaluation time. Storing a concrete
# sector here would be a lie that survives into attribution.
FUND_SECTOR = "(fund)"

SECTOR_CODE: dict[str, str] = {
    "Information Technology": "SEC-IT",
    "Health Care": "SEC-HC",
    "Financials": "SEC-FIN",
    "Consumer Discretionary": "SEC-CD",
    "Communication Services": "SEC-COM",
    "Industrials": "SEC-IND",
    "Consumer Staples": "SEC-CS",
    "Energy": "SEC-ENE",
    "Utilities": "SEC-UTL",
    "Real Estate": "SEC-RE",
    "Materials": "SEC-MAT",
}
