
#!/usr/bin/env bash

set -euo pipefail



echo "Claude will resume at 1:05 AM. Leave laptop awake, plugged in, and do not close this terminal."



python - <<'PY'

from datetime import datetime, timedelta

from zoneinfo import ZoneInfo

import time



tz = ZoneInfo("Asia/Beirut")

now = datetime.now(tz)

run_at = now.replace(hour=1, minute=5, second=0, microsecond=0)



if run_at <= now:

    run_at += timedelta(days=1)



seconds = int((run_at - now).total_seconds())

print(f"Sleeping until {run_at} Asia/Beirut, about {seconds//3600}h {(seconds%3600)//60}m.")

time.sleep(seconds)

PY



claude --permission-mode acceptEdits -c -p "Continue the most recent Claude Code session in this project. You were interrupted by the session limit while implementing Phase 6a shadow-period work. make sure no work is corrupted and continue where you left off" 

