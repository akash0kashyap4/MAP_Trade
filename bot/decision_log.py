"""
DecisionLog - a structured trail of EVERY gate the bot checks before placing
(or rejecting) a trade. Persisted to the signals table and broadcast to the
dashboard so you can see exactly why each trade did or didn't fire.

Each entry has:
  stage   - one of: GUARD, AI, EXECUTION
  step    - short label, e.g. "VIX", "FirstCandleBlock", "AI_Decision"
  status  - PASS | BLOCK | INFO | ERROR
  detail  - human-readable explanation with the actual numbers
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class LogEntry:
    stage: str
    step: str
    status: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionLog:
    instrument: str
    time: str
    entries: list[LogEntry] = field(default_factory=list)
    ai_response: Optional[dict] = None
    outcome: Optional[dict] = None

    def guard_pass(self, step: str, detail: str = "", **data):
        self.entries.append(LogEntry("GUARD", step, "PASS", detail, data))

    def guard_block(self, step: str, detail: str = "", **data):
        self.entries.append(LogEntry("GUARD", step, "BLOCK", detail, data))

    def info(self, step: str, detail: str = "", **data):
        self.entries.append(LogEntry("INFO", step, "INFO", detail, data))

    def error(self, step: str, detail: str = "", **data):
        self.entries.append(LogEntry("GUARD", step, "ERROR", detail, data))

    def set_ai(self, decision: dict, prompt_summary: str = ""):
        self.ai_response = {
            "action":        decision.get("action"),
            "confidence":    decision.get("confidence"),
            "trend_read":    decision.get("trend_read"),
            "entry_trigger": decision.get("entry_trigger"),
            "reasoning":     decision.get("reasoning"),
            "sl_premium":    decision.get("sl_premium"),
            "target_premium": decision.get("target_premium"),
            "risk_reward":   decision.get("risk_reward"),
            "prompt_summary": prompt_summary,
        }
        self.entries.append(LogEntry(
            "AI", "AI_Decision",
            "PASS" if decision.get("action") in ("BUY_CE", "BUY_PE") else "INFO",
            f"{decision.get('action')} conf={decision.get('confidence')}/10",
            {"reasoning": decision.get("reasoning", "")[:200]},
        ))

    def finalize(self, result: str, detail: str = "", **data):
        self.outcome = {"result": result, "detail": detail, **data}
        self.entries.append(LogEntry("EXECUTION", "Outcome", "INFO", f"{result} - {detail}", data))

    def to_dict(self) -> dict:
        return {
            "instrument": self.instrument,
            "time":       self.time,
            "entries":    [asdict(e) for e in self.entries],
            "ai":         self.ai_response,
            "outcome":    self.outcome,
        }

    def summary_lines(self) -> list[str]:
        """One-per-line human readable summary, used for console/dashboard."""
        icon = {"PASS": "[OK]   ", "BLOCK": "[BLOCK]", "INFO": "[INFO] ", "ERROR": "[ERR]  "}
        out = [f"=== {self.instrument} @ {self.time} ==="]
        for e in self.entries:
            out.append(f"  {icon.get(e.status,'[?]'):8} {e.step:24} {e.detail}")
        if self.ai_response:
            ai = self.ai_response
            out.append(f"  AI -> {ai.get('action')} (conf {ai.get('confidence')}/10)")
            if ai.get("trend_read"):
                out.append(f"        trend:   {ai['trend_read']}")
            if ai.get("entry_trigger"):
                out.append(f"        trigger: {ai['entry_trigger']}")
            if ai.get("reasoning"):
                out.append(f"        reason:  {ai['reasoning'][:160]}")
        if self.outcome:
            out.append(f"  FINAL -> {self.outcome['result']}: {self.outcome.get('detail','')}")
        return out

    def summary_text(self) -> str:
        return "\n".join(self.summary_lines())
