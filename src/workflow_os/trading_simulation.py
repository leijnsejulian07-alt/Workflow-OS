from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

SIMULATION_POLICY_VERSION = "trading-simulation-policy/1"
ALLOWED_SIMULATION_ENGINES = {"vibetrading", "workflow_os"}
MAX_STRATEGY_ID_CHARS = 128
MAX_SYMBOLS = 64
MAX_SYMBOL_CHARS = 32


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _nonnegative(value: object) -> float | None:
    number = _finite(value)
    return number if number is not None and number >= 0 else None


def _positive(value: object) -> float | None:
    number = _finite(value)
    return number if number is not None and number > 0 else None


def _sha256(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    digest = value.strip()
    if len(digest) != 64 or digest.lower() != digest:
        return None
    try:
        int(digest, 16)
    except ValueError:
        return None
    return digest


def _timestamp(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _symbol_list(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= MAX_SYMBOLS:
        return None
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        symbol = item.strip().upper()
        if not symbol or len(symbol) > MAX_SYMBOL_CHARS:
            return None
        if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./" for ch in symbol):
            return None
        normalized.append(symbol)
    if len(set(normalized)) != len(normalized):
        return None
    return tuple(normalized)


@dataclass(frozen=True)
class TradingBacktestEvidence:
    strategy_id: str
    engine: str
    engine_version: str
    symbols: tuple[str, ...]
    starting_balance_eur: float
    ending_balance_eur: float
    realized_pnl_eur: float
    fees_eur: float
    max_drawdown_pct: float
    trade_count: int
    slippage_bps: float
    evidence_sha256: str
    observed_at: str
    proves_received_cash: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["symbols"] = list(self.symbols)
        return data


@dataclass(frozen=True)
class FundedAccountRuleProfile:
    provider: str
    account_ref: str
    automation_allowed: bool
    official_api_verified: bool
    max_daily_loss_eur: float
    max_total_drawdown_eur: float
    max_position_notional_eur: float
    max_leverage: float
    allowed_symbols: tuple[str, ...]
    rules_evidence_sha256: str
    checked_at: str
    production_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["allowed_symbols"] = list(self.allowed_symbols)
        return data


@dataclass(frozen=True)
class TradingSimulationDecision:
    strategy_id: str
    decision: str
    reasons: tuple[str, ...]
    may_continue_simulation: bool
    may_enter_live_execution: bool
    backtest_realized_pnl_eur: float
    max_drawdown_pct: float
    policy_version: str = SIMULATION_POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


def normalize_backtest(raw: dict[str, Any]) -> TradingBacktestEvidence:
    """Normalize hostile backtest output without treating it as cash evidence."""
    strategy_id = raw.get("strategy_id")
    if not isinstance(strategy_id, str) or not strategy_id.strip() or len(strategy_id.strip()) > MAX_STRATEGY_ID_CHARS:
        raise ValueError("strategy_id is required and bounded")

    engine = raw.get("engine")
    if engine not in ALLOWED_SIMULATION_ENGINES:
        raise ValueError("simulation engine is not allowlisted")

    engine_version = raw.get("engine_version")
    if not isinstance(engine_version, str) or not engine_version.strip() or len(engine_version.strip()) > 64:
        raise ValueError("engine_version is required and bounded")

    symbols = _symbol_list(raw.get("symbols"))
    if symbols is None:
        raise ValueError("symbols are invalid")

    starting = _positive(raw.get("starting_balance_eur"))
    ending = _nonnegative(raw.get("ending_balance_eur"))
    pnl = _finite(raw.get("realized_pnl_eur"))
    fees = _nonnegative(raw.get("fees_eur"))
    drawdown = _nonnegative(raw.get("max_drawdown_pct"))
    slippage = _nonnegative(raw.get("slippage_bps"))
    trade_count = raw.get("trade_count")
    evidence = _sha256(raw.get("evidence_sha256"))
    observed = _timestamp(raw.get("observed_at"))

    if None in (starting, ending, pnl, fees, drawdown, slippage):
        raise ValueError("backtest economics are invalid")
    assert starting is not None and ending is not None and pnl is not None and drawdown is not None
    assert fees is not None and slippage is not None
    if drawdown > 100:
        raise ValueError("max_drawdown_pct must be <= 100")
    if not isinstance(trade_count, int) or isinstance(trade_count, bool) or trade_count < 0 or trade_count > 10_000_000:
        raise ValueError("trade_count is invalid")
    if evidence is None:
        raise ValueError("evidence_sha256 is invalid")
    if observed is None:
        raise ValueError("observed_at must be timezone-aware")

    calculated_pnl = ending - starting
    tolerance = max(0.01, abs(starting) * 1e-9)
    if abs(calculated_pnl - pnl) > tolerance:
        raise ValueError("realized_pnl_eur does not match ending minus starting balance")

    return TradingBacktestEvidence(
        strategy_id=strategy_id.strip(),
        engine=engine,
        engine_version=engine_version.strip(),
        symbols=symbols,
        starting_balance_eur=starting,
        ending_balance_eur=ending,
        realized_pnl_eur=pnl,
        fees_eur=fees,
        max_drawdown_pct=drawdown,
        trade_count=trade_count,
        slippage_bps=slippage,
        evidence_sha256=evidence,
        observed_at=observed,
    )


def normalize_funded_account_rules(raw: dict[str, Any]) -> FundedAccountRuleProfile:
    """Normalize independently verified funded-account constraints."""
    provider = raw.get("provider")
    account_ref = raw.get("account_ref")
    if not isinstance(provider, str) or not provider.strip() or len(provider.strip()) > 128:
        raise ValueError("provider is required and bounded")
    if not isinstance(account_ref, str) or not account_ref.strip() or len(account_ref.strip()) > 128:
        raise ValueError("account_ref is required and bounded")

    automation_allowed = raw.get("automation_allowed")
    api_verified = raw.get("official_api_verified")
    production_enabled = raw.get("production_enabled", False)
    if not isinstance(automation_allowed, bool) or not isinstance(api_verified, bool) or not isinstance(production_enabled, bool):
        raise ValueError("account capability flags must be boolean")

    daily_loss = _positive(raw.get("max_daily_loss_eur"))
    total_drawdown = _positive(raw.get("max_total_drawdown_eur"))
    position_notional = _positive(raw.get("max_position_notional_eur"))
    max_leverage = _positive(raw.get("max_leverage"))
    symbols = _symbol_list(raw.get("allowed_symbols"))
    evidence = _sha256(raw.get("rules_evidence_sha256"))
    checked_at = _timestamp(raw.get("checked_at"))

    if None in (daily_loss, total_drawdown, position_notional, max_leverage):
        raise ValueError("funded-account limits must be positive finite numbers")
    assert daily_loss is not None and total_drawdown is not None
    assert position_notional is not None and max_leverage is not None
    if max_leverage > 100:
        raise ValueError("max_leverage is unreasonably high")
    if symbols is None:
        raise ValueError("allowed_symbols are invalid")
    if evidence is None:
        raise ValueError("rules_evidence_sha256 is invalid")
    if checked_at is None:
        raise ValueError("checked_at must be timezone-aware")

    return FundedAccountRuleProfile(
        provider=provider.strip(),
        account_ref=account_ref.strip(),
        automation_allowed=automation_allowed,
        official_api_verified=api_verified,
        max_daily_loss_eur=daily_loss,
        max_total_drawdown_eur=total_drawdown,
        max_position_notional_eur=position_notional,
        max_leverage=max_leverage,
        allowed_symbols=symbols,
        rules_evidence_sha256=evidence,
        checked_at=checked_at,
        production_enabled=production_enabled,
    )


def evaluate_simulation(
    evidence: TradingBacktestEvidence,
    *,
    max_allowed_drawdown_pct: float = 10.0,
    min_trades: int = 30,
) -> TradingSimulationDecision:
    """Evaluate backtest evidence only; a pass can never authorize live execution."""
    max_drawdown = _positive(max_allowed_drawdown_pct)
    if max_drawdown is None or max_drawdown > 100:
        raise ValueError("max_allowed_drawdown_pct must be > 0 and <= 100")
    if not isinstance(min_trades, int) or isinstance(min_trades, bool) or not 1 <= min_trades <= 1_000_000:
        raise ValueError("min_trades is invalid")

    reasons: list[str] = []
    if evidence.realized_pnl_eur <= 0:
        reasons.append("NON_POSITIVE_BACKTEST_PNL")
    if evidence.max_drawdown_pct > max_drawdown:
        reasons.append("BACKTEST_DRAWDOWN_TOO_HIGH")
    if evidence.trade_count < min_trades:
        reasons.append("INSUFFICIENT_BACKTEST_TRADES")

    if reasons:
        return TradingSimulationDecision(
            strategy_id=evidence.strategy_id,
            decision="REJECT",
            reasons=tuple(reasons),
            may_continue_simulation=False,
            may_enter_live_execution=False,
            backtest_realized_pnl_eur=evidence.realized_pnl_eur,
            max_drawdown_pct=evidence.max_drawdown_pct,
        )

    return TradingSimulationDecision(
        strategy_id=evidence.strategy_id,
        decision="SIMULATION_PASS",
        reasons=("BACKTEST_EVIDENCE_WITHIN_SIMULATION_BOUNDS", "LIVE_EXECUTION_NOT_AUTHORIZED_BY_SIMULATION"),
        may_continue_simulation=True,
        may_enter_live_execution=False,
        backtest_realized_pnl_eur=evidence.realized_pnl_eur,
        max_drawdown_pct=evidence.max_drawdown_pct,
    )


def may_prepare_live_execution(
    decision: TradingSimulationDecision,
    rules: FundedAccountRuleProfile,
    *,
    requested_symbol: str,
    requested_notional_eur: float,
    requested_leverage: float,
) -> tuple[bool, tuple[str, ...]]:
    """Fail-closed preflight only. This function never emits or authorizes an order."""
    reasons: list[str] = []
    symbol = requested_symbol.strip().upper() if isinstance(requested_symbol, str) else ""
    notional = _positive(requested_notional_eur)
    leverage = _positive(requested_leverage)

    if decision.decision != "SIMULATION_PASS":
        reasons.append("SIMULATION_NOT_PASSED")
    if not rules.automation_allowed:
        reasons.append("FUNDED_ACCOUNT_AUTOMATION_NOT_ALLOWED")
    if not rules.official_api_verified:
        reasons.append("OFFICIAL_API_NOT_VERIFIED")
    if not rules.production_enabled:
        reasons.append("LIVE_TRADING_NOT_EXPLICITLY_ENABLED")
    if symbol not in rules.allowed_symbols:
        reasons.append("SYMBOL_NOT_ALLOWED")
    if notional is None or notional > rules.max_position_notional_eur:
        reasons.append("POSITION_NOTIONAL_EXCEEDS_LIMIT")
    if leverage is None or leverage > rules.max_leverage:
        reasons.append("LEVERAGE_EXCEEDS_LIMIT")

    if reasons:
        return False, tuple(reasons)
    return True, ("PREPARE_ONLY_ALL_ACCOUNT_GATES_PASSED",)
