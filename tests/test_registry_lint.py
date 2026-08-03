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


if __name__ == '__main__':
    unittest.main()
