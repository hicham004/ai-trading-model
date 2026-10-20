# VPS runbook — OKX WebSocket port 8443 cutoff (deadline: Oct 31, 2026)

**Audience:** the human operator, on the DigitalOcean Singapore VPS that runs
the Phase 6a shadow run (`shadow.service`, account `demo-shadow-1h`).
**Agents cannot reach the VPS**; every step here is an operator action.

## Why

OKX stops accepting WebSocket connections on port `:8443` on **Oct 31, 2026**
(public internet; colocation Nov 16). This applies to every path —
`/ws/v5/public`, `/ws/v5/business`, `/ws/v5/private` — on both the production
WS host `ws.okx.com` and the demo WS host `wspap.okx.com`. REST is unaffected.

Every WebSocket default in this repository used `:8443` until the Sprint 0
change. If the VPS keeps connecting on 8443, the public feed dies on Oct 31,
the supervisor fails closed (no entries; stale-heartbeat alert) and the shadow
run goes blind. The fix is to connect without an explicit port (implicit 443).

The URL validators already accept a port-less URL, so **Path A below works with
the code that is deployed today** — you do not need to wait for the PR merge.

## Path A — environment override (do this first, ~10 minutes)

1. **Pre-flight.** A restart rebuilds the strategy window from live candles;
   if a demo position is open, the warm-up exits it through the reviewed exit
   path (accepted demo behavior). Prefer restarting while flat.

   ```bash
   cd /path/to/ai-trading-model          # the checkout shadow.service runs from
   sudo systemctl status shadow.service --no-pager
   cat logs/shadow/heartbeat.json         # state, last candle, position
   .venv/bin/python scripts/run_demo_trading.py --status
   ```

2. **Find where the WS URLs are set.** `python-dotenv` does NOT override
   variables that systemd already exported, so an `EnvironmentFile=` value
   wins over `.env`. Update whichever file(s) define them.

   ```bash
   systemctl cat shadow.service | grep -i -E "EnvironmentFile|Environment="
   grep -n "WS_URL" .env                  # never print the rest of .env
   ```

3. **Back up, then edit** (the same file(s) found above). Set exactly:

   ```bash
   cp -p .env ".env.bak-$(date +%F)" && chmod 600 ".env.bak-$(date +%F)"
   ```

   ```dotenv
   OKX_PUBLIC_WS_URL=wss://ws.okx.com/ws/v5/public
   OKX_BUSINESS_WS_URL=wss://ws.okx.com/ws/v5/business
   OKX_DEMO_PRIVATE_WS_URL=wss://wspap.okx.com/ws/v5/private
   ```

   Leave every other line untouched. Do not paste secrets anywhere.

4. **Verify the new values pass the fail-closed validators offline.**

   ```bash
   .venv/bin/python - <<'PY'
   from app.config import Settings
   from app.exchange.okx_public_ws import validate_public_ws_url
   from app.exchange.okx_demo_endpoints import validate_demo_ws_url
   s = Settings()
   print(validate_public_ws_url(s.okx_public_ws_url, expected_path="/ws/v5/public"))
   print(validate_public_ws_url(s.okx_business_ws_url, expected_path="/ws/v5/business"))
   print(validate_demo_ws_url(s.okx_demo_private_ws_url, expected_path="/ws/v5/private"))
   PY
   ```

   All three lines must print a `wss://...` URL **without** `:8443`. If a
   value comes from a systemd `EnvironmentFile`, the gate check in step 5
   (which runs under the service environment if you start it via systemd)
   is the authoritative confirmation.

5. **Gate check, then restart.**

   ```bash
   .venv/bin/python scripts/run_shadow_period.py --gate-check   # expect armable=True
   sudo systemctl restart shadow.service
   sudo systemctl status shadow.service --no-pager
   ```

6. **Confirm it is really on 443.**

   ```bash
   sudo ss -tnp | grep python | grep -E ":443|:8443"    # expect :443 only
   journalctl -u shadow.service -n 300 --no-pager \
     | grep -i -E "candle1H|subscribe|login|authenticated|reconcil|error|8443"
   cat logs/shadow/heartbeat.json                       # state=running, fresh timestamp
   ```

   Within about one hour the heartbeat's last-candle timestamp must advance
   by one 1H bar (that is the proof of `candle1H` delivery on the new URL).
   Warm-up needs ~30 live 1H candles, so the first possible signal is ~30h
   after the restart. A Telegram notification should arrive as usual if
   notifications are configured.

7. **Rollback** (only if the service fails to start): restore the backup and
   restart. Do not fall back to `:8443` after Oct 31 — it will not connect.

   ```bash
   cp -p ".env.bak-$(date +%F)" .env && sudo systemctl restart shadow.service
   ```

## Path B — after the Sprint 0 PR is merged (code defaults are port-less)

1. `git fetch && git status` — confirm a clean checkout on `main`, then
   `git pull` (never a feature branch on the VPS).
2. Reinstall dependencies — `requirements.txt` is now a hashed lockfile and
   includes Alembic:

   ```bash
   .venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e .
   ```

3. One-time: bring the existing database under Alembic without changing it
   (the tables already exist from `create_all`; see
   `docs/runbooks/DB_MIGRATIONS.md`):

   ```bash
   .venv/bin/alembic current          # expect: no revision yet
   .venv/bin/alembic stamp head
   .venv/bin/alembic current          # expect: 0001 (head)
   ```

4. `--gate-check`, restart, and verify exactly as in Path A steps 5–6. The
   `.env` overrides from Path A can stay (they now equal the defaults).

## Also while you are on the VPS (Sprint 0 deliverable 3)

Copy the July → October shadow daily reports and journals off the VPS for
the evidence summary, then redact before anything is committed (no account
names beyond `demo-shadow-1h`, no key fingerprints, no IPs, no tokens):

```bash
# run from your laptop
mkdir -p docs/evidence/shadow-2026-07-to-10
scp 'vps:/path/to/ai-trading-model/logs/shadow/report-*.md' docs/evidence/shadow-2026-07-to-10/
scp 'vps:/path/to/ai-trading-model/logs/shadow/journal-*.jsonl' docs/evidence/shadow-2026-07-to-10/
```

Hand the folder to an agent session for the one-page summary (entries,
fills, PnL, restarts, alerts). Nothing in this runbook changes trading scope:
demo-only, `x-simulated-trading: 1`, long-only SPOT, `ma_crossover` untouched.
