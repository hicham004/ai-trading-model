# VPS runbook — move the shadow run off OKX WebSocket port 8443

**Audience:** the human operator, on the DigitalOcean Singapore VPS that runs
the Phase 6a shadow run (`shadow.service`, account `demo-shadow-1h`).
**Agents cannot reach the VPS**; every step here is an operator action.
Rewritten 2026-11-04; the earlier version of this runbook (Sprint 0) was wrong
in one important way, explained under "Why a new account name".

## Where things stand (checked 2026-11-04)

OKX announced that WebSocket port `:8443` is discontinued (public internet
from Oct 31, 2026; the changelog entry was last updated 2026-10-22). On
2026-11-04 both `wss://ws.okx.com:8443/ws/v5/public` and
`wss://wspap.okx.com:8443/ws/v5/public` still accepted connections, but every
connection was answered first with the notice *"WebSocket port 8443 will be
retired soon. Please migrate to port 443"*. So the shadow run is probably still
alive today, and it will go blind on a day OKX does not announce in advance.
REST is unaffected. The fix is to connect without an explicit port (443).

Every WebSocket default in this repository used `:8443` until the Sprint 0
change (on `plan/auto`, not yet merged). The VPS runs `main`, so its code
defaults still say `:8443`; the `.env` values below override them.

## Why a new account name

`app/execution/identity.py` puts the three WebSocket URLs into the demo
account's **immutable identity**. When a stored account is opened with
different URLs, `DemoStore.ensure_account` raises `AccountIdentityMismatch`
("use a new --account name") and the gate fails closed. So changing the URLs
for `demo-shadow-1h` makes that account refuse to start. The earlier runbook's
claim that the override "works with the code deployed today" was wrong (found
2026-10-26, verified against the code the VPS runs, with a throwaway database).

The right move is a **new account name**, `demo-shadow-1h-443`, with the new
URLs. Two consequences you should know:

- The new account's first reconcile records the venue balances as its fixed
  baseline (`app/execution/reconcile.py`, the balance cross-check: venue
  balances must always equal that baseline plus the account's own fills). The
  old account must be stopped first and must never trade again.
  `demo-shadow-1h` keeps its history in the database; nothing is deleted.
- **The old account must be flat.** A position left open under
  `demo-shadow-1h` is not exited by the new account's warm-up: the new account
  starts with no stored position, its baseline simply includes that BTC, and
  the runtime can never sell it (selling it by hand in the OKX demo UI would
  show up as an unexplained balance change and halt the run). So flatness is a
  precondition of the switch, not a preference.
- Until the old account's fills are older than OKX's 3-day `/trade/fills`
  window, the new account's gate reports `WRONG ACCOUNT SCOPE` and stays
  `armable=False`. That is the fail-closed design, not a fault: wait, then run
  the gate again. (`demo-shadow-1h` traded rarely, one round trip in June, so
  this is usually already satisfied.)

## Steps (about 15 minutes, plus a possible 3-day wait)

1. **Pre-flight: the old account MUST be flat; note the last fill.**

   ```bash
   cd /path/to/ai-trading-model            # the checkout shadow.service runs from
   sudo systemctl status shadow.service --no-pager
   cat logs/shadow/heartbeat.json          # REQUIRED: "flat_at_lot": true, state=running
   grep -h '"fill"' logs/shadow/journal-*.jsonl | tail -n 3    # the newest fill_time, if any (3-day window)
   ls -t logs/shadow/report-*.md | head -n 1                 # the latest daily report also lists fills
   .venv/bin/python scripts/run_demo_trading.py --status    # runtime flags: armed, kill switch, reconcile_consistent
   ```

   If `flat_at_lot` is **false**, do not change the account name yet. Either
   wait for the strategy's own exit, or restart the service once under the OLD
   name and the OLD settings (`sudo systemctl restart shadow.service`): the
   warm-up rebuilds the strategy window and exits the open position through the
   reviewed exit path (accepted demo behaviour). Wait for the exit fill, check
   `"flat_at_lot": true` and `reconcile_consistent: True`, then continue.

2. **Find where the settings live.** `python-dotenv` does NOT override
   variables that systemd already exported, so an `EnvironmentFile=` value
   wins over `.env`. Edit whichever file defines them.

   ```bash
   systemctl cat shadow.service | grep -i -E "EnvironmentFile|Environment="
   grep -n -E "WS_URL|DEMO_ACCOUNT_NAME" .env     # never print the rest of .env
   ```

3. **Stop the service, back up, then edit.** Set exactly these five values in
   the file(s) found above; leave every other line untouched, paste no secrets.

   ```bash
   sudo systemctl stop shadow.service
   cp -p .env ".env.bak-$(date +%F)" && chmod 600 ".env.bak-$(date +%F)"
   ```

   ```dotenv
   OKX_PUBLIC_WS_URL=wss://ws.okx.com/ws/v5/public
   OKX_BUSINESS_WS_URL=wss://ws.okx.com/ws/v5/business
   OKX_DEMO_PRIVATE_WS_URL=wss://wspap.okx.com/ws/v5/private
   DEMO_ACCOUNT_NAME=demo-shadow-1h-443
   SHADOW_PERIOD_ENABLED=1
   ```

   The account-partition guard passes because the name is set explicitly.

4. **Check the URLs offline** (no network, no keys used).

   ```bash
   .venv/bin/python - <<'PY'
   from app.config import Settings
   from app.exchange.okx_public_ws import validate_public_ws_url
   from app.exchange.okx_demo_endpoints import validate_demo_ws_url
   s = Settings()
   print(s.demo_account_name)
   print(validate_public_ws_url(s.okx_public_ws_url, expected_path="/ws/v5/public"))
   print(validate_public_ws_url(s.okx_business_ws_url, expected_path="/ws/v5/business"))
   print(validate_demo_ws_url(s.okx_demo_private_ws_url, expected_path="/ws/v5/private"))
   PY
   ```

   Expect `demo-shadow-1h-443` and three `wss://...` URLs **without** `:8443`.
   If the values live in a systemd `EnvironmentFile` rather than `.env`, load
   that file into your shell first, for this check and for step 5 (otherwise
   both would read the old settings and gate-check the old account):

   ```bash
   set -a; . /path/to/the/EnvironmentFile; set +a     # the file found in step 2
   ```

5. **Gate check.** This is the new account's first authenticated contact: it
   creates the account row with the new identity and records the baseline.

   ```bash
   .venv/bin/python scripts/run_shadow_period.py --gate-check
   ```

   - `armable=True`: go to step 6.
   - `armable=False` with `WRONG ACCOUNT SCOPE` in the issues: the old
     account's fills are still inside OKX's 3-day window. Leave the service
     stopped, come back after 3 full days from the last fill, run the gate
     again. Nothing trades meanwhile; in demo that costs nothing.
   - Any other issue: do not start the service; keep the output (no secrets in
     it) for an agent session.

6. **Start and confirm it really runs on 443.**

   ```bash
   sudo systemctl start shadow.service
   sudo systemctl status shadow.service --no-pager
   sudo ss -tnp | grep python | grep -E ":443|:8443"     # expect :443 only
   journalctl -u shadow.service -n 300 --no-pager \
     | grep -i -E "candle1H|subscribe|login|authenticated|reconcil|error|8443|identity"
   cat logs/shadow/heartbeat.json                         # state=running, fresh timestamp
   ```

   Within about one hour the heartbeat's last-candle timestamp must advance by
   one 1H bar (the proof of `candle1H` delivery on the new URL). Warm-up needs
   about 30 live 1H candles, so the first possible signal is about 30 hours
   after the start. A Telegram notification arrives as usual if notifications
   are configured.

7. **Rollback** (only if the service fails to start for a reason other than
   `WRONG ACCOUNT SCOPE`): restore the backup and start. Do not stay on
   `:8443` any longer than needed: it stops working on a day OKX chooses.

   ```bash
   cp -p "$(ls -t .env.bak-* | head -n 1)" .env && sudo systemctl start shadow.service   # the newest backup
   ```

8. **Tell the agents.** In the next agent session, say that G1 is done, so
   `CLAUDE.md` ("Active demo account") and `docs/PLAN_STATUS.md` can be
   updated to `demo-shadow-1h-443`. The old account's reports and journals
   stay valid evidence.

## After the Sprint 0 pull request is merged (code defaults are port-less)

1. `git fetch && git status`: a clean checkout on `main`, then `git pull`
   (never a feature branch on the VPS).
2. Reinstall dependencies: `requirements.txt` is now a hashed lockfile and
   includes Alembic.

   ```bash
   .venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e .
   ```

3. One-time: bring the existing database under Alembic without changing it
   (the tables already exist from `create_all`; see
   `docs/runbooks/DB_MIGRATIONS.md`).

   ```bash
   .venv/bin/alembic current          # expect: no revision yet
   .venv/bin/alembic stamp head
   .venv/bin/alembic current          # expect: 0001 (head)
   ```

4. `--gate-check`, restart, and verify exactly as in steps 5 and 6. The `.env`
   values from step 3 can stay: the URLs now equal the defaults, and the
   account name must stay `demo-shadow-1h-443` (the identity is fixed).

## Also while you are on the VPS (plan row G4)

Copy the July to October shadow daily reports and journals off the VPS for the
evidence summary (plan row R11), then redact before anything is committed (no
account names beyond `demo-shadow-1h`, no key fingerprints, no IPs, no tokens):

```bash
# run from your laptop
mkdir -p docs/evidence/shadow-2026-07-to-10
scp 'vps:/path/to/ai-trading-model/logs/shadow/report-*.md' docs/evidence/shadow-2026-07-to-10/
scp 'vps:/path/to/ai-trading-model/logs/shadow/journal-*.jsonl' docs/evidence/shadow-2026-07-to-10/
```

Hand the folder to an agent session for the one-page summary (entries, fills,
PnL, restarts, alerts). Nothing in this runbook changes trading scope:
demo-only, `x-simulated-trading: 1`, long-only SPOT, `ma_crossover` untouched.
