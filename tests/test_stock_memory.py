from __future__ import annotations

import json
from datetime import UTC, datetime

from app.diagnostic_export import build_diagnostic_export
from app.evidence.store import EvidenceStore
from app.market_data import HistoricalDataStore
from app.models import Side
from app.research_team import (
    FundDecision,
    ResearchContextBuilder,
    ResearchReport,
    ResearchRole,
    ResearchTeam,
)
from app.stock_memory import StockMemoryStore


class MemoryAwareFakeLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_structured(self, prompt: str, response_model):
        self.prompts.append(prompt)
        if response_model is ResearchReport:
            role = next(
                (
                    candidate
                    for candidate in ResearchRole
                    if f"{candidate.value} analyst" in prompt
                    or f"{candidate.value} research role" in prompt
                ),
                ResearchRole.MANAGER,
            )
            return ResearchReport(
                role=role,
                score=0.3,
                confidence=0.7,
                summary="Maintain the current plan while evidence remains constructive",
            )
        if response_model is FundDecision:
            return FundDecision(
                action=Side.BUY,
                target_allocation_pct=0.03,
                confidence=0.72,
                horizon="2-8 weeks",
                thesis="Accumulate gradually while the thesis remains intact",
                stop_price=95.0,
                target_price=120.0,
            )
        raise AssertionError("unexpected response model")


def test_research_team_persists_and_reuses_strategy_memory(tmp_path) -> None:
    now = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
    evidence = EvidenceStore(tmp_path / "evidence.sqlite3")
    context = ResearchContextBuilder(HistoricalDataStore(), evidence)
    llm = MemoryAwareFakeLLM()
    team = ResearchTeam(llm, context)  # type: ignore[arg-type]

    team.run("TCS", now)

    store = StockMemoryStore(tmp_path / "stock-memory.sqlite3")
    saved = store.recent_for_symbol("TCS")
    assert len(saved) == 1
    assert saved[0].action == "BUY"
    assert saved[0].thesis == "Accumulate gradually while the thesis remains intact"
    assert saved[0].stop_price == 95.0
    assert saved[0].target_price == 120.0

    llm.prompts.clear()
    team.run("TCS", now.replace(hour=11))

    combined_prompts = "\n".join(llm.prompts)
    assert "PRIOR STRATEGY MEMORY" in combined_prompts
    assert "Accumulate gradually while the thesis remains intact" in combined_prompts


def test_diagnostic_export_contains_stock_strategy_memory(tmp_path) -> None:
    now = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
    store = StockMemoryStore(tmp_path / "stock-memory.sqlite3")
    from app.stock_memory import StockMemory

    store.append(
        StockMemory(
            id=None,
            symbol="TCS",
            recorded_at=now,
            action="BUY",
            confidence=0.8,
            target_allocation_pct=0.04,
            horizon="2-8 weeks",
            thesis="Buy on improving earnings momentum",
            manager_summary="Constructive with controlled downside",
            evidence_ids=("evidence-1",),
            stop_price=95.0,
            target_price=125.0,
        )
    )

    payload = json.loads(build_diagnostic_export(tmp_path, 100_000))

    assert payload["schema_version"] == 3
    assert len(payload["stock_strategy_memory"]) == 1
    memory = payload["stock_strategy_memory"][0]
    assert memory["symbol"] == "TCS"
    assert memory["action"] == "BUY"
    assert memory["thesis"] == "Buy on improving earnings momentum"
