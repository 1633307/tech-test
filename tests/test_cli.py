"""
Pruebas para el CLI (punto de entrada).
Verifica que los comandos y parámetros requeridos por el enunciado se procesen correctamente.
"""

import unittest
from unittest.mock import patch

from src.cli import build_parser, main


class TestCLI(unittest.TestCase):
    """Verificación de argumentos de línea de comandos."""

    def setUp(self):
        self.parser = build_parser()

    def test_import_command_parses_feed_path(self):
        args = self.parser.parse_args(["import", "data/feed_dia1.csv"])
        self.assertEqual(args.command, "import")
        self.assertEqual(args.feed_path, "data/feed_dia1.csv")

    def test_sync_command_parses_without_extra_args(self):
        args = self.parser.parse_args(["sync"])
        self.assertEqual(args.command, "sync")

    def test_status_command_parses_product_id(self):
        args = self.parser.parse_args(["status", "8090"])
        self.assertEqual(args.command, "status")
        self.assertEqual(args.product_id, "8090")

    @patch("src.cli.handle_import")
    def test_main_dispatches_import(self, mock_handle):
        mock_handle.return_value = 0
        exit_code = main(["import", "data/feed_dia1.csv"])
        self.assertEqual(exit_code, 0)
        mock_handle.assert_called_once_with("data/feed_dia1.csv")

    @patch("src.cli.handle_sync")
    def test_main_dispatches_sync(self, mock_handle):
        mock_handle.return_value = 0
        exit_code = main(["sync"])
        self.assertEqual(exit_code, 0)
        mock_handle.assert_called_once()

    @patch("src.cli.handle_status")
    def test_main_dispatches_status(self, mock_handle):
        mock_handle.return_value = 0
        exit_code = main(["status", "8090"])
        self.assertEqual(exit_code, 0)
        mock_handle.assert_called_once_with("8090")


if __name__ == "__main__":
    unittest.main()
