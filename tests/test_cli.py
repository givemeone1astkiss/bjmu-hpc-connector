from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

from bjmu_hpc_connector import cli


class ConfigTests(unittest.TestCase):
    def test_defaults_and_route(self) -> None:
        with patch.dict(os.environ, {"BHC_USER": "test_user"}, clear=True):
            config = cli.load_config()

        self.assertEqual(config.bastion, "10.100.0.88")
        self.assertEqual(config.sftp_target, "10.100.0.5")
        self.assertEqual(config.otp_entry, "otp/aidd")
        self.assertEqual(config.default_node, 5)
        self.assertEqual(config.sftp_route, "test_user/10.100.0.5/test_user@10.100.0.88")

    def test_configuration_overrides(self) -> None:
        environment = {
            "BHC_USER": "user-1",
            "BHC_BASTION": "gateway.example",
            "BHC_SFTP_TARGET": "target.example",
            "BHC_OTP_ENTRY": "otp/cluster",
            "BHC_NODE_PREFIX": "node",
            "BHC_DEFAULT_NODE": "3",
            "BHC_OTP_TIMEOUT": "12.5",
        }
        with patch.dict(os.environ, environment, clear=True):
            config = cli.load_config()

        self.assertEqual(config.node_prefix, "node")
        self.assertEqual(config.default_node, 3)
        self.assertEqual(config.otp_timeout, 12.5)

    def test_user_is_required(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(cli.ConnectError):
                cli.load_config()

    def test_default_node_range_is_validated(self) -> None:
        with patch.dict(os.environ, {"BHC_USER": "user", "BHC_DEFAULT_NODE": "8"}, clear=True):
            with self.assertRaises(cli.ConnectError):
                cli.load_config()


class PromptTests(unittest.TestCase):
    def test_sftp_credential_is_password_plus_otp(self) -> None:
        read_fd, write_fd = os.pipe()
        try:
            automation = cli.Automation(mode="sftp", otp="123456", node="")
            with patch.dict(os.environ, {"DEFAULT_PWD": "example-password"}, clear=True):
                automation.feed(b"Password: ", write_fd)
            os.close(write_fd)
            write_fd = -1
            self.assertEqual(os.read(read_fd, 1024), b"example-password 123456\n")
        finally:
            os.close(read_fd)
            if write_fd >= 0:
                os.close(write_fd)

    def test_ssh_asset_selection(self) -> None:
        read_fd, write_fd = os.pipe()
        try:
            automation = cli.Automation(mode="ssh", otp="123456", node="login05")
            automation.auth_sent = True
            automation.feed(
                "  1: 10.0.0.1 login01\n  5: 10.0.0.5 login05\n请选择目标资产：".encode(),
                write_fd,
            )
            os.close(write_fd)
            write_fd = -1
            self.assertEqual(os.read(read_fd, 1024), b"login05\n")
        finally:
            os.close(read_fd)
            if write_fd >= 0:
                os.close(write_fd)


class ParserTests(unittest.TestCase):
    def test_numeric_node_option(self) -> None:
        with patch.object(sys, "argv", ["bhc", "ssh", "-N", "3"]):
            args = cli.parse_args()
        self.assertEqual(args.node, 3)

    def test_sftp_has_no_auth_option(self) -> None:
        with patch.object(sys, "argv", ["bhc", "sftp", "--auth", "otp"]):
            with self.assertRaises(SystemExit):
                cli.parse_args()


if __name__ == "__main__":
    unittest.main()
