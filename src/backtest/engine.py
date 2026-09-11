import numpy as np
import pandas as pd
import logging
from src.backtest.risk import BookRiskPolicy

logger = logging.getLogger(__name__)


def run_backtest(
    signals: np.ndarray,
    da_prices: np.ndarray,
    system_sell_price: np.ndarray,
    system_buy_price: np.ndarray,
    timestamps=None,
    cost_per_trade: float = 0.1,
    starting_capital: float = 50_000.0,
    risk_pct: float = 0.02,
    max_drawdown_pct: float = 0.20,
    max_book_exposure_pct: float = 1.00,
    mid_prices: np.ndarray | None = None,
    predicted_spreads: np.ndarray | None = None,
    baseline_hedge_ratio: float = 0.15,
    take_profit_pct: float = 0.90,
    stop_loss_price_delta: float = 5.00,
    slippage: float = 2.00,
    sizing_prices: np.ndarray | None = None,
    settlement_publication_lag_h: float = 1.0,
    book_risk_policy: BookRiskPolicy | None = None,
) -> tuple:
    """Run backtest for a Day-Ahead Auction vs Imbalance settlement strategy.

    Position sizing is account-based and committed per *auction book*:
        position_mwh = (auction_capital × risk_pct) / max(abs(sizing_price), 10)
    where auction_capital is the equity standing when that delivery day's book
    was bid. Every contract for a market date is sized from the same figure,
    because they were all committed at the same auction; the day's realised P&L
    becomes available only after delivery ends plus the publication lag. The book is scaled back pro-rata
    if its total notional would exceed max_book_exposure_pct of that equity.

    The simulation halts at an auction boundary if the account has breached the
    loss floor relative to initial capital (not a trailing peak drawdown):
        floor = starting_capital × (1 − max_drawdown_pct)

    PnL per settlement period (in £, not per-MWh):
        LONG  (signal= 1): (SSP − DA) × position_mwh − cost × position_mwh
        SHORT (signal=-1): (DA − SBP) × position_mwh − cost × position_mwh
        NEUTRAL (0):        0

    Args:
        signals:            1 = Long DA, −1 = Short DA, 0 = Neutral.
        da_prices:          Day-ahead price (£/MWh).
        system_sell_price:  Imbalance SSP (£/MWh).
        system_buy_price:   Imbalance SBP (£/MWh).
        timestamps:         UTC timestamps for daily aggregation (optional).
        cost_per_trade:       Transaction cost (£/MWh of position).
        starting_capital:     Initial account equity (£).
        risk_pct:             Fraction of auction equity to commit per trade.
        max_drawdown_pct:     Halt threshold — fraction of starting capital lost.
        max_book_exposure_pct: Cap on one delivery day's total notional as a
                              fraction of auction equity.
        mid_prices:           Intraday market index price series (£/MWh).
        predicted_spreads:    Raw model spread forecasts (£/MWh).
        baseline_hedge_ratio: Fraction of position hedged at execution (0–1).
        take_profit_pct:      Take-profit trigger as a fraction of predicted spread.
        stop_loss_price_delta: Adverse-move trigger (£/MWh); the adjusted-MID fill can exceed it.
        slippage:             Bid-ask crossing cost applied to intraday mid-price exits (£/MWh).
        sizing_prices:        Pre-auction reference prices; defaults to a fixed £50/MWh.
                              Cleared DA prices never determine the bid quantity.
        settlement_publication_lag_h: Assumed delay after the delivery day ends (1 hour).
        book_risk_policy: Optional common stress budget and drawdown sizing policy.

    Returns:
        (net_pnl, trading_metrics)
        net_pnl — per-period absolute PnL array (£), length == len(signals)

        trading_metrics carries an execution ledger (executed MWh and fees per
        period) so cost and gross figures are read off the fills themselves.
    """
    if not 0.0 <= baseline_hedge_ratio <= 1.0:
        raise ValueError(
            f"baseline_hedge_ratio must be between 0 and 1, got {baseline_hedge_ratio}"
        )

    signals = np.asarray(signals, dtype=int)
    da_prices = np.asarray(da_prices, dtype=float)
    sys_sell = np.asarray(system_sell_price, dtype=float)
    sys_buy = np.asarray(system_buy_price, dtype=float)
    n = len(signals)

    if not (len(da_prices) == len(sys_sell) == len(sys_buy) == n):
        raise ValueError("All input arrays must have the same length")

    sizing = np.full(n, 50.0) if sizing_prices is None else np.asarray(sizing_prices, dtype=float)
    if len(sizing) != n or not np.isfinite(sizing).all():
        raise ValueError("sizing_prices must contain one finite pre-auction reference per row")
    if not np.isfinite(settlement_publication_lag_h) or settlement_publication_lag_h < 0:
        raise ValueError("settlement_publication_lag_h must be non-negative and finite")

    _mid: np.ndarray | None = None
    _pred: np.ndarray | None = None
    if mid_prices is not None and predicted_spreads is not None:
        _mid = np.asarray(mid_prices, dtype=float)
        _pred = np.asarray(predicted_spreads, dtype=float)
        if len(_mid) != n or len(_pred) != n:
            raise ValueError(
                "mid_prices and predicted_spreads must have the same length as signals"
            )

    _SLIPPAGE = slippage

    # ------------------------------------------------------------------
    # Auction-book position sizing
    #
    # Every delivery period of market date D is committed at one auction, on
    # D-1. So the whole book for D is sized from the equity standing at that
    # auction, and the day's realised P&L only moves the equity that sizes the
    # *next* auction.
    #
    # Sizing period-by-period and compounding capital inside the day, as this
    # used to, lets a contract's quantity respond to settlement outcomes from
    # earlier contracts on the same delivery day — outcomes that on the model's
    # own commercial timeline were still hours away when the book was bid. On a
    # two-contract probe that showed up as the second contract's P&L moving from
    # £200 to £204 purely because the *first* contract's cash-out price changed,
    # with the second contract's own prices untouched. The drawdown halt moved
    # the same way: it cancelled entries that were already committed.
    # ------------------------------------------------------------------
    drawdown_floor = starting_capital * (1.0 - max_drawdown_pct)
    current_capital = starting_capital
    # `settled_capital` is equity observable at the auction being sized;
    # `pending_pnl` holds the book that is delivering but has not settled yet.
    settled_capital = starting_capital
    settled_peak = starting_capital
    pending_books: list[tuple[pd.Timestamp, float, float]] = []
    risk_book_ledger = []
    net_pnl = np.zeros(n, dtype=float)
    position_mwh_arr = np.zeros(n, dtype=float)
    fee_paid_arr = np.zeros(n, dtype=float)
    halted_at = None
    halt_details = None

    _active_tp_count = 0
    _active_sl_count = 0
    _active_imbalance_count = 0

    if timestamps is not None:
        _ts = pd.DatetimeIndex(pd.to_datetime(timestamps, utc=True))
        if len(_ts) != n or _ts.hasnans or not _ts.is_monotonic_increasing:
            raise ValueError("timestamps must be finite, chronological and match the input length")
        book_key = _ts.tz_convert("Europe/London").normalize()
    else:
        # Without timestamps there is no way to tell one auction from the next,
        # so the entire input is treated as a single committed book rather than
        # silently reintroducing intraday compounding.
        book_key = pd.Index(np.zeros(n, dtype=int))

    order = np.argsort(book_key.values, kind="stable")
    books: dict = {}
    for i in order:
        books.setdefault(book_key[i], []).append(i)

    for book_id in sorted(books, key=lambda k: (k is None, k)):
        idx = books[book_id]
        if timestamps is not None:
            # Calendar arithmetic preserves 10:30 London across DST transitions.
            auction = (
                book_id.tz_localize(None)
                - pd.Timedelta(days=1)
                + pd.Timedelta(hours=10, minutes=30)
            ).tz_localize("Europe/London")
            for available, pnl, _ in sorted(pending_books):
                if available <= auction:
                    settled_capital += pnl
                    settled_peak = max(settled_peak, settled_capital)
            pending_books = [
                (available, pnl, stress)
                for available, pnl, stress in pending_books
                if available > auction
            ]

        # The halt reads the same observable equity as the sizing rule: a book
        # cannot be withheld on the strength of a settlement that has not landed.
        if settled_capital <= drawdown_floor:
            halted_at = int(idx[0])
            halt_details = {
                "auction_time": auction.isoformat() if timestamps is not None else None,
                "first_unbid_delivery_time": (
                    _ts[halted_at].isoformat() if timestamps is not None else None
                ),
                "settled_equity": float(settled_capital),
                "booked_equity": float(current_capital),
                "capital_floor": float(drawdown_floor),
            }
            logger.warning(
                "Initial-capital loss floor reached at auction %s "
                "(settled equity £%.0f ≤ floor £%.0f); no new books, "
                "already committed books remain in PnL",
                halt_details["auction_time"],
                settled_capital,
                drawdown_floor,
            )
            break

        # Release dated settlements before risk checks, even across empty days/gaps.
        auction_capital = settled_capital

        tradable = [
            i
            for i in idx
            if signals[i] != 0
            and not (np.isnan(da_prices[i]) or np.isnan(sys_sell[i]) or np.isnan(sys_buy[i]))
        ]
        if not tradable:
            continue

        # Use the pre-auction reference floored at £10 so negative or near-zero prices
        # (which occurred in GB in 2018/2019) don't invert or inflate position size.
        sizes = {i: (auction_capital * risk_pct) / max(abs(sizing[i]), 10.0) for i in tradable}

        # Aggregate exposure budget for the book. Sizing each contract at a fixed
        # fraction of equity is a per-trade rule; a day that fires many of them
        # still has to fit inside one balance sheet, so the book is scaled back
        # pro-rata if its total notional would exceed the budget.
        notional = sum(sizes[i] * max(abs(sizing[i]), 10.0) for i in tradable)
        budget = auction_capital * max_book_exposure_pct
        if notional > budget > 0:
            scale = budget / notional
            sizes = {i: q * scale for i, q in sizes.items()}

        committed_stress = 0.0
        if book_risk_policy is not None:
            # Charge all gross MWh against the same adverse-move scenario.
            # No credit for expected netting or for which exit looks safer.
            stress_per_mwh = (
                book_risk_policy.stress_move_gbp_per_mwh + abs(cost_per_trade) + abs(slippage)
            )
            pending_stress = sum(stress for _, _, stress in pending_books)
            loss_budget = book_risk_policy.new_book_budget(
                auction_capital, settled_peak, pending_stress
            )
            requested_stress = sum(sizes.values()) * stress_per_mwh
            risk_scale = min(1.0, loss_budget / requested_stress) if requested_stress > 0 else 0.0
            sizes = {i: q * risk_scale for i, q in sizes.items()}
            committed_stress = sum(sizes.values()) * stress_per_mwh
            risk_book_ledger.append(
                {
                    "auction_time": auction.isoformat() if timestamps is not None else None,
                    "delivery_day": str(book_id),
                    "available_equity": float(auction_capital),
                    "settled_peak": float(settled_peak),
                    "drawdown_scale": book_risk_policy.scale(auction_capital, settled_peak),
                    "pending_stress": float(pending_stress),
                    "new_book_budget": float(loss_budget),
                    "new_book_stress": float(committed_stress),
                    "gross_mwh": float(sum(sizes.values())),
                }
            )
            if committed_stress <= 0:
                continue

        book_pnl = 0.0
        for i in tradable:
            position_mwh = sizes[i]

            if (
                _mid is not None
                and _pred is not None
                and not (np.isnan(_mid[i]) or np.isnan(_pred[i]))
            ):
                # ----------------------------------------------------------
                # Hybrid execution: passive baseline slice + active choice slice
                # ----------------------------------------------------------
                passive_mwh = position_mwh * baseline_hedge_ratio
                active_mwh = position_mwh * (1.0 - baseline_hedge_ratio)
                da = da_prices[i]
                pred_spread = _pred[i]

                if signals[i] == 1:  # LONG — exit by selling
                    mid_adj = _mid[i] - _SLIPPAGE
                    passive_pnl = passive_mwh * (mid_adj - da)

                    # Reconstruct absolute fair-value target for the active slice
                    tp_level = da + pred_spread * take_profit_pct
                    loss_per_mwh = da - mid_adj  # positive when mid has fallen
                    tp_hit = mid_adj >= tp_level
                    sl_hit = loss_per_mwh >= stop_loss_price_delta
                    if tp_hit or sl_hit:
                        active_exit = mid_adj
                        # TP takes precedence when both fire (exit price is
                        # identical; only the classification differs).
                        if tp_hit:
                            _active_tp_count += 1
                        elif sl_hit:
                            _active_sl_count += 1
                    else:
                        active_exit = sys_sell[i]
                        _active_imbalance_count += 1
                    active_pnl = active_mwh * (active_exit - da)

                else:  # SHORT — exit by buying
                    mid_adj = _mid[i] + _SLIPPAGE
                    passive_pnl = passive_mwh * (da - mid_adj)

                    # Reconstruct absolute fair-value target for the active slice
                    tp_level = da - abs(pred_spread) * take_profit_pct
                    loss_per_mwh = mid_adj - da  # positive when mid has risen
                    tp_hit = mid_adj <= tp_level
                    sl_hit = loss_per_mwh >= stop_loss_price_delta
                    if tp_hit or sl_hit:
                        active_exit = mid_adj
                        # TP takes precedence when both fire (exit price is
                        # identical; only the classification differs).
                        if tp_hit:
                            _active_tp_count += 1
                        elif sl_hit:
                            _active_sl_count += 1
                    else:
                        active_exit = sys_buy[i]
                        _active_imbalance_count += 1
                    active_pnl = active_mwh * (da - active_exit)

                gross = passive_pnl + active_pnl
            else:
                # ----------------------------------------------------------
                # Baseline: full position rolls into imbalance cash-out
                # ----------------------------------------------------------
                if signals[i] == 1:
                    gross = position_mwh * (sys_sell[i] - da_prices[i])
                else:
                    gross = position_mwh * (da_prices[i] - sys_buy[i])

            # Fees are charged on the MWh actually traded, and recorded per fill
            # so the cost line can be reported from the same ledger the P&L comes
            # from rather than re-derived from a trade count.
            fee = cost_per_trade * position_mwh
            net = gross - fee

            net_pnl[i] = net
            position_mwh_arr[i] = position_mwh
            fee_paid_arr[i] = fee
            book_pnl += net

        # The book settles as a whole, but its result only becomes *available* to
        # size a later book once a full delivery day has passed — the auction for
        # the next day has already closed by the time this one finishes settling.
        current_capital += book_pnl
        if timestamps is not None:
            available = (book_id.tz_localize(None) + pd.Timedelta(days=1)).tz_localize(
                "Europe/London"
            )
            available += pd.Timedelta(hours=settlement_publication_lag_h)
            pending_books.append((available, book_pnl, committed_stress))

    final_capital = starting_capital + float(np.sum(net_pnl))
    total_return_pct = (final_capital - starting_capital) / starting_capital

    # ------------------------------------------------------------------
    # Daily aggregation (Europe/London market dates)
    # ------------------------------------------------------------------
    daily_pnl = None
    daily_returns = None
    daily_summary = {}

    if timestamps is not None:
        ts = pd.DatetimeIndex(pd.to_datetime(timestamps, utc=True))
        market_date = ts.tz_convert("Europe/London").normalize()
        daily_pnl = pd.Series(net_pnl, index=market_date, name="net_pnl").groupby(level=0).sum()
        # Percentage returns on opening account equity, including booked PnL.
        # This differs from settled equity available at the earlier auction. Position
        # size scales with equity, so cash P&L is not a stationary series: a £500
        # day early on and a £500 day at three times the capital are different
        # results, and a Sharpe built on pounds treats them as identical.
        opening_equity = starting_capital + daily_pnl.cumsum().shift(1).fillna(0.0)
        daily_returns = (daily_pnl / opening_equity).replace([np.inf, -np.inf], np.nan).dropna()
        if len(daily_pnl) > 0:
            daily_summary = {
                "mean_daily_pnl": float(daily_pnl.mean()),
                "std_daily_pnl": float(daily_pnl.std()),
                "best_day_pnl": float(daily_pnl.max()),
                "worst_day_pnl": float(daily_pnl.min()),
                "positive_days": int((daily_pnl > 0).sum()),
                "negative_days": int((daily_pnl < 0).sum()),
                "total_days": int(len(daily_pnl)),
            }

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------
    # Executions, not intentions. ``signals != 0`` counts every proposal the
    # model made, including periods skipped for missing prices and every period
    # after a capital halt; using it as the denominator of win rate and as the
    # liquidity filter credited the strategy with trades it never took.
    executed = position_mwh_arr > 0
    n_active = int(executed.sum())
    n_proposed = int((signals != 0).sum())

    executed_pnl = net_pnl[executed]
    total_pnl = float(np.sum(net_pnl))
    mean_pnl = float(np.mean(executed_pnl)) if len(executed_pnl) > 0 else 0.0

    total_mwh = float(position_mwh_arr.sum())
    total_fees = float(fee_paid_arr.sum())
    gross_pnl = total_pnl + total_fees

    # Sharpe on daily *percentage* returns — the natural unit for a once-per-day
    # auction decision on a compounding account. Power markets trade every
    # calendar day, so annualise with sqrt(365) rather than sqrt(252).
    #
    # `sharpe_cash` is the old pounds-based figure, retained and named honestly
    # so the two are never confused for one another.
    sharpe_ratio = 0.0
    sharpe_cash = 0.0
    if daily_returns is not None and len(daily_returns) > 1 and float(daily_returns.std()) > 0:
        sharpe_ratio = float(daily_returns.mean() / daily_returns.std() * np.sqrt(365))
    if daily_pnl is not None and len(daily_pnl) > 1 and float(daily_pnl.std()) > 0:
        sharpe_cash = float(daily_pnl.mean() / daily_pnl.std() * np.sqrt(365))
    if sharpe_ratio == 0.0 and daily_returns is None and len(net_pnl) > 1:
        if float(np.std(net_pnl)) > 0:
            sharpe_cash = float(np.mean(net_pnl) / np.std(net_pnl) * np.sqrt(48 * 365))

    # Drawdown on the equity curve, which starts at the opening balance.
    #
    # Running the high-water mark over cumulative P&L alone starts it at the
    # first period's result, so an account whose very first trade loses £200 is
    # already at its own peak and reports a £0 maximum drawdown. Seeding the
    # curve with starting capital makes the first loss a loss.
    equity = starting_capital + np.cumsum(net_pnl)
    equity_path = np.concatenate(([starting_capital], equity))
    running_max = np.maximum.accumulate(equity_path)
    drawdowns = equity_path - running_max
    max_drawdown = float(np.min(drawdowns)) if n > 0 else 0.0
    peak_dd_pct = float(np.min(drawdowns / running_max)) if n > 0 else 0.0

    # Win / loss
    win_mask = executed & (net_pnl > 0)
    loss_mask = executed & (net_pnl < 0)
    win_rate = float(win_mask.sum()) / n_active if n_active > 0 else 0.0
    avg_win = float(np.mean(net_pnl[win_mask])) if win_mask.any() else 0.0
    avg_loss = float(np.mean(net_pnl[loss_mask])) if loss_mask.any() else 0.0

    sum_wins = float(np.sum(net_pnl[win_mask])) if win_mask.any() else 0.0
    sum_losses = float(np.sum(net_pnl[loss_mask])) if loss_mask.any() else 0.0
    # Undefined when there are no losing trades / no drawdown. Use None rather than
    # inf/nan so the metrics serialise to standards-compliant JSON (bare Infinity/NaN
    # tokens are rejected by strict parsers such as pd.read_json and JS JSON.parse).
    profit_factor = sum_wins / abs(sum_losses) if sum_losses != 0.0 else None

    max_dd_pct = abs(max_drawdown) / starting_capital if starting_capital > 0 else 0.0

    # Two different things, named as such.
    #
    # `calmar_ratio` is the conventional measure: return annualised over the
    # window, divided by the peak-relative drawdown. `return_to_dd` is the
    # window-total return over drawdown-against-opening-capital that this repo
    # used to publish *as* Calmar — kept so older runs stay comparable, but no
    # longer wearing a name that means something else in the literature.
    return_to_dd = total_return_pct / max_dd_pct if max_dd_pct > 0 else None

    years = None
    if daily_pnl is not None and len(daily_pnl) > 1:
        span_days = (daily_pnl.index.max() - daily_pnl.index.min()).days + 1
        years = span_days / 365.25
    if years and years > 0 and abs(peak_dd_pct) > 0:
        annualised_return = (final_capital / starting_capital) ** (1.0 / years) - 1.0
        calmar_ratio = annualised_return / abs(peak_dd_pct)
    else:
        annualised_return = None
        calmar_ratio = None

    n_long = int((signals == 1).sum())
    n_short = int((signals == -1).sum())
    n_neutral = int((signals == 0).sum())

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    logger.info("Backtest complete (auction-book sizing)")
    logger.info("  Starting capital: £%s", f"{starting_capital:>10,.0f}")
    logger.info(
        "  Final capital:    £%s  (%+.1f%%)", f"{final_capital:>10,.0f}", total_return_pct * 100
    )
    logger.info("  Total PnL:        £%s", f"{total_pnl:>10,.2f}")
    logger.info("  Sharpe:            %.3f", sharpe_ratio)
    logger.info(
        "  Profit factor:     %s", f"{profit_factor:.2f}" if profit_factor is not None else "n/a"
    )
    logger.info("  Max drawdown:     £%s", f"{max_drawdown:>10,.2f}")
    logger.info("  Win rate:          %.1f%%", win_rate * 100)
    logger.info("  Executed trades:  %d of %d proposed", n_active, n_proposed)
    logger.info("  Traded volume:    %s MWh", f"{total_mwh:>10,.1f}")
    logger.info("  Transaction cost: £%s", f"{total_fees:>10,.2f}")
    if halted_at is not None:
        logger.warning("  Simulation HALTED at period %d of %d", halted_at, n)
    if daily_summary:
        logger.info(
            "  Daily PnL — Mean: £%.0f  Std: £%.0f  Best: £%.0f  Worst: £%.0f  (+%d/-%d days)",
            daily_summary["mean_daily_pnl"],
            daily_summary["std_daily_pnl"],
            daily_summary["best_day_pnl"],
            daily_summary["worst_day_pnl"],
            daily_summary["positive_days"],
            daily_summary["negative_days"],
        )

    trading_metrics = {
        "starting_capital": starting_capital,
        "final_capital": final_capital,
        "total_return_pct": total_return_pct,
        "total_pnl": total_pnl,
        "n_trades": n_active,
        "n_signals_proposed": n_proposed,
        "total_position_mwh": total_mwh,
        "total_transaction_costs": total_fees,
        "gross_pnl": gross_pnl,
        "win_rate": win_rate,
        "avg_trade": mean_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "calmar_ratio": calmar_ratio,
        "annualised_return_pct": annualised_return,
        "return_to_dd": return_to_dd,
        "sharpe_ratio": sharpe_ratio,
        "sharpe_cash": sharpe_cash,
        "max_drawdown": max_drawdown,
        "max_drawdown_pct_peak": peak_dd_pct,
        "halted_at_period": halted_at,
        "halt_details": halt_details,
        "risk_book_ledger": risk_book_ledger,
        "signal_distribution": {
            "long": n_long,
            "short": n_short,
            "neutral": n_neutral,
        },
        "daily_summary": daily_summary,
        "execution_breakdown": {
            "total_active_trades": n_active,
            "active_tp_triggered": _active_tp_count,
            "active_sl_triggered": _active_sl_count,
            "active_rode_to_imbalance": _active_imbalance_count,
        },
    }

    return net_pnl, trading_metrics


def run_backtest_from_dataframe(
    df: pd.DataFrame,
    signal_col: str = "signal",
    da_price_col: str = "day_ahead_price",
    sell_price_col: str = "system_sell_price",
    buy_price_col: str = "system_buy_price",
    time_col: str = "time",
    mid_price_col: str | None = None,
    predicted_spread_col: str | None = None,
    cost_per_trade: float = 0.1,
    starting_capital: float = 50_000.0,
    risk_pct: float = 0.02,
    max_drawdown_pct: float = 0.20,
    max_book_exposure_pct: float = 1.00,
    baseline_hedge_ratio: float = 0.15,
    take_profit_pct: float = 0.90,
    stop_loss_price_delta: float = 5.00,
    slippage: float = 2.00,
    sizing_prices: np.ndarray | None = None,
    settlement_publication_lag_h: float = 1.0,
    book_risk_policy: BookRiskPolicy | None = None,
) -> tuple:
    """Convenience wrapper: run backtest from a DataFrame and attach per-period PnL."""
    order = df[time_col].argsort(kind="stable").to_numpy()
    if sizing_prices is not None:
        sizing_prices = np.asarray(sizing_prices, dtype=float)
        if len(sizing_prices) != len(df):
            raise ValueError("sizing_prices must contain one pre-auction reference per row")
        sizing_prices = sizing_prices[order]
    df = df.iloc[order].copy().reset_index(drop=True)
    timestamps = df[time_col].values if time_col in df.columns else None
    mid_prices = df[mid_price_col].values if mid_price_col and mid_price_col in df.columns else None
    predicted_spreads = (
        df[predicted_spread_col].values
        if predicted_spread_col and predicted_spread_col in df.columns
        else None
    )

    net_pnl, metrics = run_backtest(
        signals=df[signal_col].values,
        da_prices=df[da_price_col].values,
        system_sell_price=df[sell_price_col].values,
        system_buy_price=df[buy_price_col].values,
        timestamps=timestamps,
        cost_per_trade=cost_per_trade,
        starting_capital=starting_capital,
        risk_pct=risk_pct,
        max_drawdown_pct=max_drawdown_pct,
        max_book_exposure_pct=max_book_exposure_pct,
        mid_prices=mid_prices,
        predicted_spreads=predicted_spreads,
        baseline_hedge_ratio=baseline_hedge_ratio,
        take_profit_pct=take_profit_pct,
        stop_loss_price_delta=stop_loss_price_delta,
        slippage=slippage,
        sizing_prices=sizing_prices,
        settlement_publication_lag_h=settlement_publication_lag_h,
        book_risk_policy=book_risk_policy,
    )

    df["pnl"] = net_pnl
    return df, metrics
