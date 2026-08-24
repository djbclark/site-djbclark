from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANAGED_CLIENT = "/usr/local/bin/sudo-secretspec"
ACTIVE_SECRET_DOCS = (
    ROOT / "README.md",
    ROOT / "justfile",
    ROOT / "human" / "API-KEYS-E4.md",
    ROOT / "human" / "HANDOFF-HUMAN.md",
    ROOT / "roles" / "goose" / "README.md",
    ROOT / "roles" / "litellm" / "README.md",
    ROOT / "roles" / "site_agents" / "README.md",
    ROOT / "services" / "twilio-webhook-relay" / "README.md",
    ROOT / "docs" / "OPS-RELEASES.md",
    ROOT / "docs" / "plans" / "collie-caddy-integration-plan.md",
    ROOT / "inventory" / "hosts.yml",
    ROOT / "registry" / "ports.yml",
    ROOT / "registry" / "paths.yml",
)
DIRECT_CALL = re.compile(r"(?<![-/\w])secretspec\s+(?:--file\s+\S+\s+)?(?:get|set|run|export|check|add|delete)\b")
OBSOLETE_STORE = re.compile(r"(?:site-djbclark|site-private)/\.env|~?/\.config/secretspec(?:\.toml|/config\.toml)")


class SecretSpecAntiDriftPolicyTest(unittest.TestCase):
    def test_active_instructions_use_only_managed_client(self) -> None:
        failures: list[str] = []
        for path in ACTIVE_SECRET_DOCS:
            text = path.read_text(encoding="utf-8")
            if "SUPERSEDED / HISTORICAL — DO NOT EXECUTE AS WRITTEN" in text:
                continue
            for line_number, line in enumerate(text.splitlines(), 1):
                if DIRECT_CALL.search(line) or OBSOLETE_STORE.search(line):
                    failures.append(f"{path.relative_to(ROOT)}:{line_number}: {line.strip()}")
        self.assertEqual(failures, [], "active SecretSpec bypasses remain:\n" + "\n".join(failures))

    def test_public_managed_client_examples_include_reason(self) -> None:
        operation = re.compile(r"sudo-secretspec\s+(?:get|set|run|export|check|add|delete)\b")
        failures: list[str] = []
        for path in ACTIVE_SECRET_DOCS:
            text = path.read_text(encoding="utf-8")
            if "SUPERSEDED / HISTORICAL — DO NOT EXECUTE AS WRITTEN" in text:
                continue
            for line_number, line in enumerate(text.splitlines(), 1):
                if operation.search(line) and "--reason" not in line:
                    failures.append(f"{path.relative_to(ROOT)}:{line_number}: {line.strip()}")
        self.assertEqual(failures, [])

    def test_just_recipes_delegate_secret_use_to_managed_client(self) -> None:
        text = (ROOT / "justfile").read_text(encoding="utf-8")
        self.assertIn(f'{MANAGED_CLIENT} run --reason "apply LiteLLM provider keys" -- just litellm-apply', text)
        self.assertIn(f'{MANAGED_CLIENT} run --reason "apply Open WebUI secret" -- just open-webui-apply', text)

    def test_watchdog_is_scheduled_and_alert_only(self) -> None:
        jobber = (ROOT / "roles/site_agents/templates/jobber.yaml.j2").read_text(encoding="utf-8")
        watchdog = (ROOT / "roles/site_agents/templates/secretspec-drift-watchdog.sh.j2").read_text(encoding="utf-8")
        tasks = (ROOT / "roles/site_agents/tasks/main.yml").read_text(encoding="utf-8")
        defaults = (ROOT / "roles/site_agents/defaults/main.yml").read_text(encoding="utf-8")

        self.assertIn("secretspec-drift-watchdog:", jobber)
        self.assertIn("site_agents_secretspec_drift_watchdog_script", jobber)
        self.assertIn("notifyOnFailure: [*programSink, *filesystemSink]", jobber)
        self.assertIn('/usr/local/bin/sudo-secretspec-drift-check', defaults)
        self.assertIn("site_agents_secretspec_drift_checker", watchdog)
        self.assertIn("Install SecretSpec drift watchdog", tasks)
        self.assertNotRegex(watchdog, r"\b(?:rm|mv|cp|chmod|chown|ln|install)\b")

    def test_watchdog_propagates_drift_without_mutation(self) -> None:
        template = (ROOT / "roles/site_agents/templates/secretspec-drift-watchdog.sh.j2").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            checker = home / "ops/stayturgid/control/bin/sudo-secretspec-drift-check"
            checker.parent.mkdir(parents=True)
            home.mkdir(exist_ok=True)
            planted = home / "planted.toml"
            planted.write_text("do-not-touch\n", encoding="utf-8")
            checker.write_text(
                "import sys\nprint('SecretSpec drift: alternate manifest present')\nsys.exit(1)\n",
                encoding="utf-8",
            )
            rendered = template.replace(
                "{{ site_agents_secretspec_drift_checker | quote }}", repr(str(checker))
            ).replace("{{ site_agents_home | quote }}", repr(str(home))).replace(
                "{{ (site_agents_home ~ '/ops') | quote }}", repr(str(home / "ops"))
            )
            script = root / "watchdog"
            script.write_text(rendered, encoding="utf-8")
            script.chmod(0o755)
            before = planted.stat()

            result = subprocess.run([script], capture_output=True, text=True, check=False)

            after = planted.stat()
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertIn("SecretSpec drift: alternate manifest present", result.stderr)
            self.assertEqual(planted.read_text(encoding="utf-8"), "do-not-touch\n")
            self.assertEqual((before.st_dev, before.st_ino, before.st_mtime_ns), (after.st_dev, after.st_ino, after.st_mtime_ns))

    def test_jobber_alerts_use_managed_client_and_inbox_topic(self) -> None:
        notifier = (ROOT / "roles/site_agents/templates/jobber-notify.py.j2").read_text(encoding="utf-8")
        self.assertIn(MANAGED_CLIENT, notifier)
        self.assertNotIn('"--format"', notifier)
        self.assertIn('"message_thread_id": 22158', notifier)
        self.assertNotIn('send_drift_via_hermes', notifier)
        self.assertIn('info["job_name"] != "secretspec-drift-watchdog"', notifier)
        self.assertIn("env = {}", notifier)
        self.assertNotIn("dict(os.environ)", notifier)
        self.assertNotIn("site-djbclark/.env", notifier)
        self.assertNotIn("open(env_file", notifier)


if __name__ == "__main__":
    unittest.main()
