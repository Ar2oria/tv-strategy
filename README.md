# TradingView indicators and local validation

This repository preserves the original Pine Script indicators and adds a local
Python event-study environment for `vix_cheat`.

## Original indicators

- `smart_money/main.ps`: LuxAlgo Smart Money Concepts, Pine v5.
- `vix_cheat/main.ps`: KioseffTrading VIX Cheat Sheet, Pine v5.

Both are `indicator()` scripts, not executable `strategy()` backtests.

## Python validation

- [Environment and reproduction guide](python_validation/README.md)
- [Chinese SOXX validation summary](reports/SOXX_VALIDATION_ZH.md)
- [Full price-return report](reports/SOXX_20161104_20261104_close_validation.md)
- [Dividend-adjusted robustness report](reports/SOXX_20161104_20261104_adj_close_validation.md)
- [NKVI1! versus VIX weekly comparison](reports/nkvi1/NKVI1_SOXX_WEEKLY_ZH.md)
- [NKVI1!, NKVI2!, and VIX full weekly comparison](reports/nkvi2/NKVI2_SOXX_WEEKLY_ZH.md)
- [Four-source comparison including VXSMH](reports/vxsmh/VXSMH_SOXX_WEEKLY_ZH.md)
- [Volatility versus MACD/MA: global mechanism study](reports/global_research/SOXX_SIGNAL_MECHANISMS_ZH.md)
- [VKI1!, VKI2!, and VKOSPI spot comparison](reports/vki/VKI_SOXX_WEEKLY_ZH.md)

## Local indicator validation system

A separate full-stack app lives in `backend/` and `frontend/`: a FastAPI + SQLite
service that stores multi-market daily bars and can serve a React interface for
chart-based indicator validation, Task scheduling, and hot settings.

- Design and plans: `docs/superpowers/specs/` and `docs/superpowers/plans/`
- Backend: `backend/README.md` (own `.venv`, providers, API, Task framework)
- Frontend: `frontend/README.md` (build, single-port production serving, E2E)

Nothing in the directories below is reused or modified by that app.

Quick checks from the repository root:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m python_validation.cli \
  --asset SOXX --start 2016-11-04 --end 2026-11-04 \
  --volatilities VIX VXSMH --frequencies daily weekly \
  --return-column close
```

Downloaded market data and virtual-environment files are intentionally excluded
from Git. Generated event details, summaries, and reports remain available for
review.
