# Agent Handoff

## Environment Status

The development workstation is ready for Phase 1 research work.

- Windows 11 Home, build 26200
- WSL 2 with Ubuntu 26.04 LTS
- Docker Desktop 4.76.0 with the WSL 2 backend
- Docker Engine 29.5.2
- Docker integration enabled for Ubuntu
- Docker `hello-world` verification passed from Windows and Ubuntu
- VS Code with the WSL, Python, Codex, and Claude Code extensions
- Ubuntu user: `aitec` with password-protected `sudo`

## Installed Tools

Windows:

- Git 2.54.0
- Python 3.14.5
- Node.js 24.16.0
- npm 11.13.0
- Docker 29.5.2
- VS Code 1.123.0
- Codex
- Claude Code

Ubuntu/WSL:

- Git 2.53.0
- Python 3.14.4
- Node.js 22.22.1
- npm 9.2.0
- Docker 29.5.2

## Project Location

The canonical working repository is:

```text
/home/aitec/ai-trading-model
```

Use this Linux-home copy for development. Do not use the fallback Windows copy
under `/mnt/c/Users/aitec/OneDrive/Desktop/ai-trading-model`, because
Windows-mounted repositories can have slower file I/O and more permission or
symlink friction in WSL.

## Repository Status

- Git repository initialized on branch `main`
- No Git remote configured
- Setup and safety files only
- No trading-system scaffold or implementation exists
- No real `.env` file or credentials exist
- This handoff is included in the initial setup checkpoint

## Safety Rules

- No real trading in Phase 1
- Public OKX market data only
- No OKX private API keys or account access
- No live order execution or order placement
- No withdrawals ever
- No martingale
- No doubling down or automated loss chasing
- Every future strategy must be backtested
- Backtest results do not authorize paper or live execution
- The risk manager has final veto over every future simulated, paper, or live
  trading action
- Never commit secrets or put real values in `.env.example`

## Next Task For Claude Code

The following prompt is future work. It has not been executed as part of the
setup checkpoint.

```text
Claude Code, read CLAUDE.md, PROJECT_RULES.md, README.md, and docs/AGENT_HANDOFF.md before doing anything.

Build Phase 1 only for this AI-assisted OKX trading research system.

Phase 1 scope:
- Python FastAPI backend
- public OKX REST market data client only
- fetch candles for BTC-USDT and ETH-USDT
- PostgreSQL database through Docker
- SQLAlchemy models for candles
- script to fetch and store candles
- simple Streamlit dashboard to view stored candles
- basic backtest skeleton with fake strategy only
- logging
- tests
- README instructions

Hard restrictions:
- no OKX private API keys
- no account access
- no live trading
- no order placement
- no leverage
- no withdrawals
- no strategy claiming profitability
- no hidden secrets
- no editing .env with real values

After building, run tests and show me exactly how to run the project.
```
