# Optional OpenClaw Integration Plan

## Status

OpenClaw is not installed, connected, or authorized for this project. This
document describes a possible future integration only.

OpenClaw could eventually provide a self-hosted messaging gateway and agent
orchestration layer. Any integration must remain outside the trading execution
path and use a narrowly restricted interface to this project.

## Possible Uses

After the core research system is stable, OpenClaw could provide:

- A Telegram or Discord command center
- A daily public-market summary
- A controlled backtest report runner
- A log summarizer
- An alert dispatcher
- An AI-agent orchestrator for approved Codex or Claude tasks

These roles are reporting, research, and development conveniences. They do not
authorize trading or access to an exchange account.

## Prohibited Capabilities

OpenClaw must never:

- Execute live trades
- Access OKX private APIs
- Read `.env` or any other secret store
- Access withdrawals or withdrawal permissions
- Access wallets, seed phrases, or private keys
- Install untrusted skills
- Bypass the risk manager
- Place orders directly

## Security Rules

- Allow only explicitly whitelisted commands.
- Run OpenClaw in a separate, limited folder and process boundary.
- Give it no access to project secrets.
- Give it no access to browser profiles.
- Give it no access to SSH keys.
- Give it no access to crypto wallets.
- Require manual security review before adding any third-party skill.
- All actions must be logged.
- Log every requested command, authorization decision, action, and result.
- Use least-privilege filesystem and network permissions.
- Treat all Telegram, Discord, and other chat input as untrusted.
- Keep OpenClaw outside the risk-manager and execution-module trust boundary.

## Proposed Future Commands

Only reviewed commands from an allowlist may be exposed:

- `/status`
- `/daily_report`
- `/run_backtest BTC-USDT 1h`
- `/show_last_trades`
- `/summarize_errors`
- `/market_snapshot`
- `/risk_report`

`/show_last_trades` may show backtest, simulation, or explicitly approved demo
trading records only. None of these commands may trigger an order, change risk
limits, reveal secrets, or expand permissions.

## Integration Boundary

A future adapter should expose a small, versioned command API rather than
giving OpenClaw general shell or repository access. The adapter should:

- Validate command names and parameters against an allowlist.
- Reject unknown instruments, intervals, file paths, and free-form commands.
- Run reports and backtests through dedicated non-privileged jobs.
- Return sanitized output that contains no credentials or sensitive paths.
- Require separate human approval for configuration or permission changes.
- Remain physically and logically unable to call exchange order endpoints.

## Recommendation

OpenClaw should only be integrated after Phase 1 and Phase 2 are stable. For
now, we only document it.
