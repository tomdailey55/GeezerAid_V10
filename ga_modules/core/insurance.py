"""
GeezerAid V10 — Insurance Quote Module

Manages insurance quote comparison:
- Store current policy details
- Research insurers and their quote processes
- Track quotes over time
- Generate comparison reports
- Identify savings opportunities
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

INSURANCE_DIR = Path.home() / ".geeza" / "insurance"
POLICY_FILE = INSURANCE_DIR / "current_policy.json"
QUOTES_FILE = INSURANCE_DIR / "quotes.json"
INSURERS_FILE = INSURANCE_DIR / "insurers.json"


@dataclass
class Vehicle:
    year: int
    make: str
    model: str
    vin: str
    premium_6mo: float = 0.0


@dataclass
class Coverage:
    bodily_injury: str = ""
    property_damage: str = ""
    medical_payments: str = ""
    pip: str = ""
    comprehensive_deductible: int = 0
    collision_deductible: int = 0
    ers: str = ""


@dataclass
class Policy:
    insurer: str
    policy_number: str
    period_start: str
    period_end: str
    premium_6mo: float
    vehicles: list
    coverage: Coverage
    drivers: list
    address: str
    discounts: list
    discounts_total: float
    
    def to_dict(self) -> dict:
        return {
            "insurer": self.insurer,
            "policy_number": self.policy_number,
            "period": f"{self.period_start} to {self.period_end}",
            "premium_6mo": self.premium_6mo,
            "premium_annual": self.premium_6mo * 2,
            "vehicles": [asdict(v) for v in self.vehicles],
            "coverage": asdict(self.coverage),
            "drivers": self.drivers,
            "address": self.address,
            "discounts": self.discounts,
            "discounts_total": self.discounts_total
        }


@dataclass
class Quote:
    insurer: str
    premium_6mo: float
    premium_annual: float
    coverage_match: str  # "exact", "better", "worse"
    notes: str
    timestamp: float
    source: str  # "online", "agent", "phone"
    
    def to_dict(self) -> dict:
        return asdict(self)


class InsuranceManager:
    """Manages insurance quotes and comparisons."""
    
    def __init__(self):
        INSURANCE_DIR.mkdir(parents=True, exist_ok=True)
        self.current_policy: Optional[Policy] = None
        self.quotes: list[Quote] = []
        self._load()
    
    def _load(self):
        """Load existing data."""
        if POLICY_FILE.exists():
            try:
                data = json.loads(POLICY_FILE.read_text())
                # Parse policy
                vehicles = [Vehicle(**v) for v in data.get("vehicles", [])]
                coverage = Coverage(**data.get("coverage", {}))
                self.current_policy = Policy(
                    insurer=data.get("insurer", ""),
                    policy_number=data.get("policy_number", ""),
                    period_start=data.get("period_start", ""),
                    period_end=data.get("period_end", ""),
                    premium_6mo=data.get("premium_6mo", 0),
                    vehicles=vehicles,
                    coverage=coverage,
                    drivers=data.get("drivers", []),
                    address=data.get("address", ""),
                    discounts=data.get("discounts", []),
                    discounts_total=data.get("discounts_total", 0)
                )
            except Exception as e:
                logger.warning(f"Failed to load policy: {e}")
        
        if QUOTES_FILE.exists():
            try:
                data = json.loads(QUOTES_FILE.read_text())
                self.quotes = [Quote(**q) for q in data.get("quotes", [])]
            except Exception as e:
                logger.warning(f"Failed to load quotes: {e}")
    
    def save_policy(self, policy: Policy):
        """Save current policy."""
        self.current_policy = policy
        POLICY_FILE.write_text(json.dumps(policy.to_dict(), indent=2))
        logger.info(f"Saved policy: {policy.insurer} {policy.policy_number}")
    
    def add_quote(self, quote: Quote):
        """Add a quote."""
        self.quotes.append(quote)
        self._save_quotes()
        logger.info(f"Added quote: {quote.insurer} ${quote.premium_6mo:.2f}/6mo")
    
    def _save_quotes(self):
        """Save quotes to file."""
        QUOTES_FILE.write_text(json.dumps({
            "quotes": [q.to_dict() for q in self.quotes],
            "updated": time.time()
        }, indent=2))
    
    def get_comparison(self) -> dict:
        """Get quote comparison."""
        if not self.current_policy:
            return {"error": "No current policy set"}
        
        baseline = self.current_policy.premium_6mo
        quotes = []
        
        for q in sorted(self.quotes, key=lambda x: x.premium_6mo):
            savings = baseline - q.premium_6mo
            savings_pct = (savings / baseline * 100) if baseline > 0 else 0
            quotes.append({
                "insurer": q.insurer,
                "premium_6mo": q.premium_6mo,
                "premium_annual": q.premium_annual,
                "savings": round(savings, 2),
                "savings_percent": round(savings_pct, 1),
                "coverage_match": q.coverage_match,
                "notes": q.notes,
                "source": q.source,
                "date": datetime.fromtimestamp(q.timestamp).strftime("%Y-%m-%d")
            })
        
        return {
            "current_policy": self.current_policy.to_dict(),
            "quotes": quotes,
            "best_quote": quotes[0] if quotes else None,
            "total_quotes": len(quotes)
        }
    
    def get_status(self) -> dict:
        """Get insurance module status."""
        return {
            "has_policy": self.current_policy is not None,
            "policy_insurer": self.current_policy.insurer if self.current_policy else None,
            "quotes_collected": len(self.quotes),
            "quote_insurers": list(set(q.insurer for q in self.quotes))
        }
