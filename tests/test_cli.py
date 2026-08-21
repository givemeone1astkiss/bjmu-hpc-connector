from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
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

    def test_vpn_configuration_does_not_require_user(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = cli.load_config(require_user=False)

        self.assertEqual(config.user, "")
        self.assertEqual(config.vpn_wait_timeout, 60)
        self.assertTrue(config.vpn_client.endswith("sslvpn-client.exe"))

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

    def test_vpn_open_wait_option(self) -> None:
        with patch.object(sys, "argv", ["bhc", "vpn-open", "--wait", "3.5"]):
            args = cli.parse_args()
        self.assertEqual(args.wait, 3.5)

    def test_vpn_setup_commands(self) -> None:
        for command in ("vpn-setup", "vpn-setup-remove"):
            with self.subTest(command=command), patch.object(sys, "argv", ["bhc", command]):
                args = cli.parse_args()
            self.assertEqual(args.mode, command)


class VpnTests(unittest.TestCase):
    def config(self) -> cli.Config:
        with patch.dict(os.environ, {}, clear=True):
            return cli.load_config(require_user=False)

    def test_status_reports_ready_route(self) -> None:
        output = io.StringIO()
        with (
            patch.object(cli, "is_wsl", return_value=True),
            patch.object(cli, "windows_vpn_process_running", return_value=True),
            patch.object(cli, "vpn_task_exists", return_value=True),
            patch.object(cli, "probe_route", return_value=(True, "via eth1")),
            patch.object(cli, "tcp_reachable", return_value=True),
            redirect_stdout(output),
        ):
            status = cli.vpn_status(self.config())

        self.assertEqual(status, 0)
        self.assertIn("VPN ready: yes", output.getvalue())
        self.assertIn("Windows SSL VPN client: running", output.getvalue())
        self.assertIn("Pre-authorized VPN task: installed", output.getvalue())

    def test_windows_child_environment_excludes_secrets(self) -> None:
        environment = {
            "PATH": "/usr/bin",
            "DEFAULT_PWD": "password",
            "GH_TOKEN": "token",
            "EXAMPLE_SECRET": "secret",
        }
        with patch.dict(os.environ, environment, clear=True):
            child_environment = cli._secret_free_environment()

        self.assertEqual(child_environment, {"PATH": "/usr/bin"})

    def test_open_does_not_duplicate_ready_client(self) -> None:
        with (
            patch.object(cli, "is_wsl", return_value=True),
            patch.object(cli, "tcp_reachable", return_value=True),
            patch.object(cli, "vpn_status", return_value=0),
            patch.object(cli, "launch_windows_vpn_client") as launch,
        ):
            status = cli.vpn_open(0, self.config())

        self.assertEqual(status, 0)
        launch.assert_not_called()

    def test_open_starts_client_and_detects_route(self) -> None:
        with (
            patch.object(cli, "is_wsl", return_value=True),
            patch.object(cli, "tcp_reachable", side_effect=[False, True]),
            patch.object(cli, "windows_vpn_process_running", return_value=False),
            patch.object(cli, "vpn_task_exists", return_value=False),
            patch.object(cli, "launch_windows_vpn_client") as launch,
            patch.object(cli, "vpn_status", return_value=0),
        ):
            status = cli.vpn_open(1, self.config())

        self.assertEqual(status, 0)
        launch.assert_called_once()

    def test_open_prefers_pre_authorized_task(self) -> None:
        with (
            patch.object(cli, "is_wsl", return_value=True),
            patch.object(cli, "tcp_reachable", side_effect=[False, True]),
            patch.object(cli, "windows_vpn_process_running", return_value=False),
            patch.object(cli, "vpn_task_exists", return_value=True),
            patch.object(cli, "run_vpn_task") as run_task,
            patch.object(cli, "launch_windows_vpn_client") as direct_launch,
            patch.object(cli, "vpn_status", return_value=0),
        ):
            status = cli.vpn_open(1, self.config())

        self.assertEqual(status, 0)
        run_task.assert_called_once_with()
        direct_launch.assert_not_called()

    def test_setup_registers_and_verifies_task(self) -> None:
        config = self.config()
        with (
            patch.object(cli, "is_wsl", return_value=True),
            patch.object(cli, "validate_vpn_client_for_task") as validate,
            patch.object(cli, "run_elevated_powershell") as elevate,
            patch.object(cli, "vpn_task_exists", return_value=True),
        ):
            status = cli.vpn_setup(config)

        self.assertEqual(status, 0)
        validate.assert_called_once_with(config.vpn_client)
        setup_script = elevate.call_args.args[0]
        self.assertIn("LogonType = 3", setup_script)
        self.assertIn("RunLevel = 1", setup_script)
        self.assertIn("AllowDemandStart", setup_script)

    def test_remove_skips_elevation_when_task_is_absent(self) -> None:
        with (
            patch.object(cli, "is_wsl", return_value=True),
            patch.object(cli, "vpn_task_exists", return_value=False),
            patch.object(cli, "run_elevated_powershell") as elevate,
        ):
            status = cli.vpn_setup_remove()

        self.assertEqual(status, 0)
        elevate.assert_not_called()

    def test_open_requires_wsl(self) -> None:
        with patch.object(cli, "is_wsl", return_value=False):
            with self.assertRaises(cli.ConnectError):
                cli.vpn_open(0, self.config())


if __name__ == "__main__":
    unittest.main()
