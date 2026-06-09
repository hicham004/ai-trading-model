"""Risk management layer.

Per PROJECT_RULES.md, the risk manager has FINAL VETO over every simulated,
paper, or (future) live trading action. Strategies only ever *recommend*; the
risk manager decides whether an entry is allowed and how large it may be.

This is a skeleton: the rules are real and enforced in simulation, and this is
the single chokepoint a future live system must also pass through.
"""
