"""The paper fleet and the tokenized-stocks recorder as services on a server.

`scripts/vps_research_setup.sh` installs both from their own checkout of plan/auto as an
unprivileged user, with the unit files in `deploy/systemd/`. These tests pin what makes that safe
next to the Phase 6a shadow run: the units are confined to their own folders, can never reach the
demo keys or the demo database, are capped and first in line for the out-of-memory killer, and the
script never acts on `shadow.service`. The script itself is exercised end to end in a systemd
container (docs/runbooks/PAPER_FLEET.md, option A1), not here.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UNITS = ROOT / "deploy" / "systemd"
SCRIPT = ROOT / "scripts" / "vps_research_setup.sh"
SERVICES = {"paper-fleet.service": "logs/paper_fleet", "xstocks-data.service": "data/lake/xstocks"}
PREFIX = "/opt/ai-trading-research"


def _settings(text: str) -> dict:
    return {line.split("=", 1)[0]: line.split("=", 1)[1] for line in text.splitlines() if "=" in line and not line.startswith("#")}


def _unit(name: str) -> dict:
    return _settings((UNITS / name).read_text(encoding="utf-8"))


def _code_lines(path: Path) -> list:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _rendered(name: str) -> str:
    """The unit as the script writes it (the same three replacements as its render_units)."""
    text = (UNITS / name).read_text(encoding="utf-8")
    text = text.replace("/path/to/ai-trading-model", PREFIX).replace("CHANGE_ME_USER", "ai-research")
    return re.sub(r"(?m)^ProtectHome=read-only$", "ProtectHome=yes", text)


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_each_research_unit_is_confined_to_its_own_folder_and_unprivileged(name):
    unit = _unit(name)
    assert unit["User"] == "CHANGE_ME_USER" and unit["Group"] == "CHANGE_ME_USER"
    assert unit["WorkingDirectory"] == "/path/to/ai-trading-model"
    assert unit["ReadWritePaths"] == f"/path/to/ai-trading-model/{SERVICES[name]}", "it may write its own folder only"
    assert {"-/path/to/ai-trading-model/.env", "-/run/postgresql"} <= set(unit["InaccessiblePaths"].split())
    assert unit["ProtectSystem"] == "strict" and unit["ProtectHome"] == "read-only"
    assert unit["NoNewPrivileges"] == "yes" and unit["CapabilityBoundingSet"] == "" and unit["PrivateTmp"] == "yes"
    assert unit["RestrictAddressFamilies"].split() == ["AF_INET", "AF_INET6", "AF_UNIX"]
    assert unit["RestartPreventExitStatus"] == "2", "a setup problem must stop the service, not loop it"
    assert unit["ExecStart"].startswith("/path/to/ai-trading-model/.venv/bin/python scripts/")
    assert "--loop" in unit["ExecStart"].split()


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_each_research_unit_yields_to_the_shadow_run(name):
    unit = _unit(name)
    assert unit["Nice"] == "10"
    assert int(unit["CPUQuota"].rstrip("%")) <= 50
    assert unit["MemoryMax"].endswith(("M", "G")) and "MemoryMax" in unit
    assert int(unit["OOMScoreAdjust"]) >= 500, "under memory pressure the kernel ends these before the shadow run"
    body = (UNITS / name).read_text(encoding="utf-8")
    assert "Environment=OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1" in body, "one thread per maths library on any core count"
    assert int(unit["TasksMax"]) >= 64, "pyarrow and numpy need threads; a tight cap crashed the recorder on 16 cores"


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_each_research_unit_holds_no_secret_and_no_demo_header(name):
    body = (UNITS / name).read_text(encoding="utf-8")
    for needle in ("x-simulated-trading", "OKX_DEMO", "OKX_API", "TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY", "EnvironmentFile=/home"):
        assert needle not in body
    unit = _settings(body)
    assert "EnvironmentFile" not in unit or unit["EnvironmentFile"].startswith("-/etc/ai-trading/")


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_the_rendered_unit_hides_every_home_folder_and_keeps_no_placeholder(name):
    text = _rendered(name)
    assert "CHANGE_ME_USER" not in text and "/path/to/ai-trading-model" not in text
    unit = _settings(text)
    assert unit["ProtectHome"] == "yes", "the checkout lives outside /home, so every home folder is hidden"
    assert unit["User"] == "ai-research" and unit["WorkingDirectory"] == PREFIX
    assert unit["ReadWritePaths"] == f"{PREFIX}/{SERVICES[name]}"


def test_the_setup_script_never_acts_on_the_shadow_run():
    lines = _code_lines(SCRIPT)
    shadow = [line for line in lines if "shadow" in line]
    assert shadow, "the script reports the shadow run's state"
    for line in shadow:
        assert not re.search(r"systemctl\s+(?:--\S+\s+)*(start|stop|restart|reload|enable|disable|mask|kill|edit|set-property)\b[^|;&]*shadow", line), line
    assert any("systemctl is-active shadow.service" in line for line in shadow)
    for line in lines:
        assert ".env" not in line, f"the script never names an environment file: {line}"
        assert "/home/" not in line, f"the script never reaches into a home folder: {line}"


def test_the_setup_script_walls_off_the_shadow_run_wherever_its_folder_lives():
    code = "\n".join(_code_lines(SCRIPT))
    # Two read-only properties of shadow.service, turned into a drop-in for both research units.
    assert "systemctl show -p WorkingDirectory --value shadow.service" in code
    assert "systemctl show -p EnvironmentFiles --value shadow.service" in code
    assert "10-shadow-off-limits.conf" in code and "InaccessiblePaths=%s" in code
    # Never our own folder or one of its parents, never a top-level or system folder the services need.
    assert '"$path"/*) continue' in code
    assert "/usr/* | /etc/*" in code


def test_the_setup_script_holds_no_secret_and_installs_from_its_own_checkout():
    text = SCRIPT.read_text(encoding="utf-8")
    for needle in ("x-simulated-trading", "OKX_DEMO", "OKX_API", "TELEGRAM", "ANTHROPIC", "ssh ", "scp "):
        assert needle not in text
    code = "\n".join(_code_lines(SCRIPT))
    assert 'PREFIX="${PREFIX:-/opt/ai-trading-research}"' in code
    assert 'SERVICE_USER="${SERVICE_USER:-ai-research}"' in code
    assert 'BRANCH="${BRANCH:-plan/auto}"' in code
    assert 'REPO_URL="${REPO_URL:-https://github.com/hicham004/ai-trading-model.git}"' in code
    assert "--shell /usr/sbin/nologin" in code and "--system" in code
    assert "pip\" install --quiet --no-cache-dir -r" in code, "the hashed lockfile, as CI installs it"
    assert "--no-deps -e" in code
    assert "scripts/run_paper_fleet.py --dry-run" in code, "the offline check runs before any service starts"
    assert "reset --quiet --keep" in code, "update puts the previous code back when the new code is refused"
    assert "\r" not in text, "a CRLF line ending would break the script on Linux"


def test_the_setup_script_writes_exactly_the_two_units_it_ships():
    code = "\n".join(_code_lines(SCRIPT))
    assert 'UNITS="paper-fleet xstocks-data"' in code
    for name in SERVICES:
        assert (UNITS / name).is_file()


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason="bash syntax check on Linux and macOS only")
def test_the_setup_script_parses():
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
