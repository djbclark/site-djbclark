import contextlib
import io
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add bin/ to path so we can import registry_lint
sys.path.append(str(Path(__file__).parent.parent / "bin"))
import registry_lint


class RegistryLintTest(unittest.TestCase):
    @patch('registry_lint.fail')
    @patch('registry_lint.sys.exit')
    @patch('registry_lint.REPO')
    def test_lint_generated_paths_catches_absolute_paths(self, mock_repo, mock_exit, mock_fail):
        mock_exit.side_effect = SystemExit
        # Create a mock path
        mock_path = MagicMock()
        mock_repo.__truediv__.return_value = mock_path
        
        mock_path.exists.return_value = True
        mock_path.is_file.return_value = True
        
        # Test 1: quoted path
        mock_path.read_text.return_value = '  path: "/srv/ops"'
        try:
            registry_lint.lint_generated_paths()
        except SystemExit:
            pass
        mock_fail.assert_called_with("generated/stayturgid/fragments/grafana/dashboards/provider.yaml:1 contains an absolute path (must use portable ${OPS_ROOT...} form)")
        
        # Test 2: cd with whitespace and quote
        mock_fail.reset_mock()
        mock_path.read_text.return_value = "    cd   '/srv/ops'"
        try:
            registry_lint.lint_generated_paths()
        except SystemExit:
            pass
        mock_fail.assert_called_with("generated/stayturgid/fragments/grafana/dashboards/provider.yaml:1 contains an absolute path (must use portable ${OPS_ROOT...} form)")

    @patch('registry_lint.fail')
    @patch('registry_lint.sys.exit')
    @patch('registry_lint.REPO')
    def test_lint_generated_paths_ignores_portable_paths(self, mock_repo, mock_exit, mock_fail):
        mock_exit.side_effect = SystemExit
        # Create a mock path
        mock_path = MagicMock()
        mock_repo.__truediv__.return_value = mock_path
        
        mock_path.exists.return_value = True
        mock_path.is_file.return_value = True
        
        # Portable paths should not fail
        mock_path.read_text.return_value = '  path: "${OPS_ROOT}/ops"'
        registry_lint.lint_generated_paths()
        mock_fail.assert_not_called()
        
        mock_path.read_text.return_value = "  cd ${OPS_ROOT}/ops"
        registry_lint.lint_generated_paths()
        mock_fail.assert_not_called()

class RegistryRoleDefaultPortsTest(unittest.TestCase):
    """Guards against litellm_port/open_webui_port silently drifting from
    registry/ports.yml -- previously nothing checked these two site-owned
    role defaults against the registry at all (2026-08-03)."""

    def _write_repo(self, tmp: Path, *, litellm_port: int = 4000, open_webui_port: int = 8085) -> None:
        (tmp / "roles" / "litellm" / "defaults").mkdir(parents=True)
        (tmp / "roles" / "litellm" / "defaults" / "main.yml").write_text(f"litellm_port: {litellm_port}\n")
        (tmp / "roles" / "open_webui" / "defaults").mkdir(parents=True)
        (tmp / "roles" / "open_webui" / "defaults" / "main.yml").write_text(f"open_webui_port: {open_webui_port}\n")
        (tmp / "registry").mkdir(parents=True)
        (tmp / "registry" / "ports.yml").write_text(
            textwrap.dedent(
                """\
                hosts:
                  mac:
                    ports:
                      - {port: 4000, bind: "127.0.0.1", owner: site, service: litellm-proxy, status: active}
                      - {port: 8085, bind: "127.0.0.1", owner: site, service: open-webui, status: active}
                """
            )
        )

    def test_matching_ports_pass(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            self._write_repo(tmp)
            with patch("registry_lint.REPO", tmp):
                findings: list[str] = []
                registry_lint.lint_role_default_ports(findings)
            self.assertEqual(findings, [])

    def test_mismatched_port_fails(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            self._write_repo(tmp, litellm_port=4001)
            with patch("registry_lint.REPO", tmp):
                findings: list[str] = []
                registry_lint.lint_role_default_ports(findings)
            self.assertEqual(len(findings), 1)
            self.assertIn("litellm_port=4001", findings[0])
            self.assertIn("port=4000", findings[0])

    def test_missing_registry_entry_fails(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            self._write_repo(tmp)
            (tmp / "registry" / "ports.yml").write_text(
                textwrap.dedent(
                    """\
                    hosts:
                      mac:
                        ports:
                          - {port: 8085, bind: "127.0.0.1", owner: site, service: open-webui, status: active}
                    """
                )
            )
            with patch("registry_lint.REPO", tmp):
                findings: list[str] = []
                registry_lint.lint_role_default_ports(findings)
            self.assertEqual(len(findings), 1)
            self.assertIn("no registry/ports.yml entry found for service 'litellm-proxy'", findings[0])


class RegistryReconcileTest(unittest.TestCase):
    """site-djbclark#107: --reconcile diffs registry/ports.yml against real
    lsof listeners. subprocess.run is mocked for lsof/ps/git so these tests
    don't depend on this machine's actual live ports."""

    LSOF_OUTPUT = (
        "p100\n" "cjava\n" "f10\n" "n127.0.0.1:10001\n"
        "p200\n" "cnode\n" "f5\n" "n127.0.0.1:20000\n"
        "p300\n" "cjava\n" "f7\n" "n127.0.0.1:30000\n"
    )
    CMDLINES = {
        "100": "java -classpath ~/.maestro/lib/* maestro.cli.AppKt mcp",
        "200": "node someOtherServer.js",
        "300": "java -classpath ~/.maestro/lib/* maestro.cli.AppKt mcp",
    }

    def _write_repo(self, tmp: Path) -> None:
        (tmp / "registry").mkdir(parents=True)
        (tmp / "registry" / "ports.yml").write_text(
            textwrap.dedent(
                """\
                hosts:
                  mac:
                    ports:
                      - {port: 10001, bind: "127.0.0.1", owner: unmanaged, service: maestro-mcp, status: active}
                      - {port: 9000, bind: "127.0.0.1", owner: site, service: stale-service, status: active}
                      - {port: 9001, bind: "127.0.0.1", owner: site, service: planned-thing, status: default-claim}
                    ephemeral_processes:
                      - pattern: "maestro.cli.AppKt mcp"
                        note: "test"
                """
            )
        )

    def _mock_subprocess_run(self, cmd, **_kwargs):
        result = MagicMock()
        if cmd[0] == "lsof":
            result.stdout = self.LSOF_OUTPUT
        elif cmd[0] == "ps":
            pid = cmd[cmd.index("-p") + 1]
            result.stdout = self.CMDLINES.get(pid, "") + "\n"
        elif cmd[0] == "git":
            result.stdout = "abc123\n"
        else:
            result.stdout = ""
        return result

    def _run_reconcile(self, tmp: Path) -> str:
        buf = io.StringIO()
        with patch("registry_lint.REPO", tmp), \
             patch("registry_lint.sys.platform", "darwin"), \
             patch("registry_lint.shutil.which", return_value="/usr/sbin/lsof"), \
             patch("registry_lint.subprocess.run", side_effect=self._mock_subprocess_run), \
             contextlib.redirect_stdout(buf):
            exit_code = registry_lint.reconcile("mac")
        self.assertEqual(exit_code, 0)  # always advisory, never fails
        return buf.getvalue()

    def test_declared_and_live_port_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            self._write_repo(tmp)
            output = self._run_reconcile(tmp)
        self.assertNotIn("10001", output)

    def test_undeclared_non_ephemeral_port_flagged(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            self._write_repo(tmp)
            output = self._run_reconcile(tmp)
        self.assertIn("live but undeclared", output)
        self.assertIn("20000", output)

    def test_undeclared_ephemeral_port_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            self._write_repo(tmp)
            output = self._run_reconcile(tmp)
        # 30000 matches the ephemeral_processes pattern via its cmdline
        self.assertNotIn("30000", output)

    def test_declared_active_but_not_listening_flagged_stale(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            self._write_repo(tmp)
            output = self._run_reconcile(tmp)
        self.assertIn("stale claim", output)
        self.assertIn("9000", output)

    def test_declared_default_claim_not_listening_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            self._write_repo(tmp)
            output = self._run_reconcile(tmp)
        # status: default-claim (not active) -- absence is expected, not stale
        self.assertNotIn("9001", output)

    def test_no_lsof_skips_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            self._write_repo(tmp)
            with patch("registry_lint.REPO", tmp), \
                 patch("registry_lint.shutil.which", return_value=None):
                exit_code = registry_lint.reconcile("mac")
            self.assertEqual(exit_code, 0)

    def test_reconcile_flag_routes_to_reconcile_not_default_lint(self):
        with patch("registry_lint.sys.argv", ["registry_lint.py", "--reconcile"]), \
             patch("registry_lint.reconcile", return_value=0) as mock_reconcile, \
             patch("registry_lint.lint_ports") as mock_lint_ports:
            exit_code = registry_lint.main()
        mock_reconcile.assert_called_once_with("mac")
        mock_lint_ports.assert_not_called()
        self.assertEqual(exit_code, 0)

    def test_no_flag_routes_to_default_lint_not_reconcile(self):
        with patch("registry_lint.sys.argv", ["registry_lint.py"]), \
             patch("registry_lint.reconcile") as mock_reconcile, \
             patch("registry_lint.lint_ports"), \
             patch("registry_lint.lint_role_default_ports"), \
             patch("registry_lint.lint_paths"), \
             patch("registry_lint.lint_generated_paths"):
            exit_code = registry_lint.main()
        mock_reconcile.assert_not_called()
        self.assertEqual(exit_code, 0)


if __name__ == '__main__':
    unittest.main()
