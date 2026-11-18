"""Exercise only shell functions; never invoke brew upgrade."""
import os
import re
import subprocess
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "roles/site_agents/templates/brew-fast-upgrade.sh.j2"


def test_paseo_is_held_with_any_override():
    source = SOURCE.read_text()
    held = re.search(r"held_casks\(\) \{.*?\n\}", source, re.S).group()
    report = re.search(r"report_sudo_casks\(\) \{.*?\n\}", source, re.S).group()
    for override in (None, "", "other", "other paseo"):
        env = dict(os.environ, MISSING_APP_CASKS="missing")
        env.pop("BREW_FAST_UPGRADE_SKIP_CASKS", None)
        if override is not None:
            env["BREW_FAST_UPGRADE_SKIP_CASKS"] = override
        script = held + "\nheld_casks"
        result = subprocess.run(["bash", "-c", script], env=env, text=True, capture_output=True, check=True)
        assert "paseo" in result.stdout.splitlines()
        # Stub every external probe; the reporting path must retain paseo too.
        script = held + "\n" + report + "\nsudo_casks() { :; }; brew() { echo paseo; }; ggrep() { grep \"$@\"; }; report_sudo_casks"
        result = subprocess.run(["bash", "-c", script], env=env, text=True, capture_output=True, check=True)
        assert "held, not upgraded" in result.stdout
        assert "paseo" in result.stdout
