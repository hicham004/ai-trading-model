"""Exchange adapters for live PUBLIC market data (Phase 3A).

This package isolates exchange-specific protocol details (currently OKX's
public WebSocket) behind a neutral interface. Adapters here only consume
UNAUTHENTICATED public market data. They never authenticate, access accounts,
place orders, or touch private endpoints.

Importing this package must never open a network connection; a connection is
only established when an adapter's ``run`` coroutine is awaited.
"""
