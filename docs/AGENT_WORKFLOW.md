# Agent Workflow And Authority

## Roles

- **Claude Code - main builder:** implements approved features, tests, and
  documentation within the current phase.
- **Codex - reviewer/tester/safety critic:** reviews code, reproduces failures,
  adds or requests adverse tests, and checks scope and security boundaries.
- **ChatGPT - architect/research/planning:** develops product architecture,
  researches options, and helps define phase requirements and acceptance
  criteria.
- **Human owner - approval and capital authority:** approves phase changes,
  security-sensitive scope, credentials, deployment, and any capital decision.

No single agent can approve its own work. Agent reports are recommendations,
not authorization.

## Standard Loop

1. Human approves a bounded task and phase scope.
2. ChatGPT or the human clarifies architecture and acceptance criteria.
3. Claude Code implements within that scope.
4. Claude runs normal and adverse tests and reports limitations.
5. Codex independently reviews and attempts to break the implementation.
6. Claude resolves accepted findings.
7. Codex verifies the fixes and documentation.
8. Human explicitly accepts or rejects phase completion.
9. A commit occurs only when requested.

## Mandatory Handoffs

Every phase-completion request must include:

- changed files;
- implemented behavior;
- safety boundaries;
- normal test results;
- adverse test results;
- unresolved findings and assumptions;
- documentation status;
- Git status; and
- a clear statement that human approval is still required.

## Prohibited Agent Actions

- Self-approving a phase.
- Treating passing tests as phase approval.
- Expanding scope without asking.
- Directly placing or approving orders.
- Requesting or exposing secrets.
- Adding private OKX access before its approved phase.
- Making a capital or live-deployment decision for the human.

## Future Runtime AI Boundary

The AI research layer may:

- summarize and classify news;
- score source quality and market impact;
- explain strategy signals;
- identify possible market regimes; and
- adjust confidence within deterministic bounds or recommend a trade block.

It may not:

- call exchange order endpoints;
- determine final position size;
- bypass the risk manager;
- override loss limits or a kill switch; or
- place, modify, or cancel orders.
