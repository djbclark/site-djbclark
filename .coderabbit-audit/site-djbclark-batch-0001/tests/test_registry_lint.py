import sys
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

if __name__ == '__main__':
    unittest.main()
