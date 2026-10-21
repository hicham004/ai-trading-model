"""Paper fleet (Sprint 5a, plan row R5a): the v1c shortlist run forward on live PUBLIC OKX data.

Every configuration of ``docs/research/paper_fleet_shortlist_v1c.json`` runs as
its own LOCAL paper account next to the controls (always-long with the policy
sizing, plain buy-and-hold), the jointly sized BTC+ETH x S1/S2/S4 portfolio and,
since plan row R5b, its allocator-v2 twin (the same sleeves; ``research.allocator``
multiplies the same sizing by a correlation cap, a weekly loss limit and a
cooldown, each between 0 and 1 of its own sizing).
Each account starts flat at the first bar that closes after the fleet was
created, trades only on bars that close after that, and writes one append-only
journal. A weekly report ranks the accounts and compares the forward numbers
with the walk-forward and holdout expectations (controls first).

Sandbox rules (the research rules, plus):

- PUBLIC data only: OKX public REST candles, funding-rate and open-interest
  history through ``app.datalake.okx_public_rest.OKXPublicRest`` (GET, an
  allowlist of public paths, no credentials ever). No authenticated endpoint,
  no demo account, no database.
- Every fill is virtual arithmetic in this package. Nothing here imports
  ``app.execution``, ``app.risk``, ``app.exchange``, ``app.okx``, ``app.paper``,
  ``app.live``, ``app.shadow`` or the strategy registry, and nothing in the
  trading runtime imports this package (``tests/test_paper_fleet_boundaries.py``).
- The rules are the research rules, unchanged: the signals come from the
  research candidates through the reviewed ``Strategy`` contract
  (:class:`research.strategies.adapters.ResearchStrategyAdapter`), and the
  bar-by-bar engine (:mod:`research.paper_fleet.engine`) is a transcription of
  :func:`research.engine.run_vectorized` that is parity-tested against it.
- Every number is a simulation. A good forward record authorizes nothing: demo
  or live use of any configuration is a separate, reviewed owner decision.
"""
