# AI Trading Model

Research-only workspace for an AI-assisted OKX crypto market project.

## Phase 1 Scope

- Collect public OKX market data.
- Store and validate research data.
- Build a backtesting skeleton.
- Add structured logs and a local dashboard.
- Develop AI agents that help with code, tests, documentation, and analysis.

Phase 1 does not include live trading, order placement, account access, or
withdrawals.

## Safety

Read `PROJECT_RULES.md` and `CLAUDE.md` before making changes. Never commit
secrets. The example environment file contains only non-secret, public-data
settings.

## Environment Checks

Windows PowerShell:

```powershell
.\scripts\check_environment.ps1
```

Ubuntu/WSL:

```bash
bash scripts/check_environment.sh
```

## Status

The Windows, WSL 2, Ubuntu, Docker, Python, Node.js, Git, VS Code, Codex, and
Claude Code development environment is ready. Trading-system implementation
has intentionally not started.
