# bjmu-hpc-connector

`bjmu-hpc-connector` provides the `bhc` command for authorized BJMU AI4DD HPC users. It obtains a TOTP from `gopass`, completes gateway authentication, selects a login node, and opens an interactive SSH or SFTP session.

## Requirements

- Linux and Python 3.10+
- BJMU VPN access
- OpenSSH client, `sshpass`, GnuPG 2.x, `gopass`, and `pipx`
- For `vpn-open`: WSL 2 with Windows interop and the BJMU-provided SafeConnect/DPtech SSL VPN client 10.1.14.0 installed on Windows

On Ubuntu or Debian:

```bash
sudo apt update
sudo apt install git gnupg openssh-client sshpass pipx curl
```

Debian-based distributions may provide an unrelated package named `gopass`. Install the official package using the [gopass setup guide](https://github.com/gopasspw/gopass/blob/master/docs/setup.md):

```bash
curl -L -q https://packages.gopass.pw/repos/gopass/gopass-archive-keyring.gpg \
  | sudo tee /usr/share/keyrings/gopass-archive-keyring.gpg >/dev/null

sudo tee /etc/apt/sources.list.d/gopass.sources >/dev/null <<'EOF'
Types: deb
URIs: https://packages.gopass.pw/repos/gopass
Suites: stable
Architectures: all amd64 arm64 armhf
Components: main
Signed-By: /usr/share/keyrings/gopass-archive-keyring.gpg
EOF

sudo apt update
sudo apt install gopass gopass-archive-keyring
```

For other systems, see the [official installation instructions](https://github.com/gopasspw/gopass#installation).

## Configure gopass

Create a GPG key if necessary, then initialize gopass:

```bash
gpg --list-secret-keys
gpg --full-generate-key  # only when no suitable key exists
gopass setup
```

Create the OTP entry in a protected editor. Paste the gateway-provided `otpauth://totp/...` URI, save, and verify that a six-digit token is returned:

```bash
gopass insert -m otp/aidd
gopass otp -o otp/aidd
```

See the [gopass OTP documentation](https://github.com/gopasspw/gopass/blob/master/docs/features.md#adding-otp-secrets) for other supported formats. Never commit the OTP URI or a gopass store to this repository.

## Environment variables

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `BHC_USER` | Yes | — | BJMU gateway and cluster username |
| `DEFAULT_PWD` | Yes | — | Static gateway password |
| `BHC_GPG_PASSPHRASE` | No | `DEFAULT_PWD` | GPG passphrase used only at an explicit pinentry prompt |
| `BHC_BASTION` | No | `10.100.0.88` | Gateway host or IP |
| `BHC_SFTP_TARGET` | No | `10.100.0.5` | Internal routed SFTP target |
| `BHC_OTP_ENTRY` | No | `otp/aidd` | gopass OTP entry |
| `BHC_DEFAULT_NODE` | No | `5` | Default node suffix (`1`–`7`) |
| `BHC_NODE_PREFIX` | No | `login` | Login asset prefix |
| `BHC_OTP_TIMEOUT` | No | `20` | gopass timeout in seconds |
| `BHC_VPN_CLIENT` | No | SafeConnect 10.1.14.0 default path | Windows VPN client executable |
| `BHC_VPN_WAIT_TIMEOUT` | No | `60` | Seconds `vpn-open` waits for the bastion route; `0` disables waiting |

Set non-secret values in your shell configuration:

```bash
export BHC_USER="your_cluster_username"
export BHC_OTP_ENTRY="otp/aidd"
export BHC_DEFAULT_NODE="5"
```

Enter secrets for the current shell instead of committing or storing them in project files:

```bash
read -rsp 'BJMU gateway password: ' DEFAULT_PWD; echo
export DEFAULT_PWD

read -rsp 'GPG passphrase (Enter to reuse gateway password): ' BHC_GPG_PASSPHRASE; echo
export BHC_GPG_PASSPHRASE
```

If `BHC_GPG_PASSPHRASE` is empty, `DEFAULT_PWD` is used to unlock gopass. The included `.env.example` is a reference only; `bhc` does not load it automatically.

## Install

```bash
pipx install .
bhc check --with-otp
```

A sanitized Codex Skill is provided at [`skills/bjmu-hpc/SKILL.md`](skills/bjmu-hpc/SKILL.md). It contains no account name, password, OTP value, or workstation identifier and relies on the environment variables above.

## Configure Windows VPN access from WSL

Install the BJMU-provided SafeConnect/DPtech SSL VPN client on Windows first. Do not install an unofficial Linux replacement or copy VPN credentials into WSL.

On Windows 11 22H2 or later, WSL 2 mirrored networking provides better VPN compatibility. Add the following to `%UserProfile%\.wslconfig` on Windows, preserving unrelated existing settings:

```ini
[wsl2]
networkingMode=mirrored
dnsTunneling=true
firewall=true
autoProxy=true
```

Apply a changed `.wslconfig` from Windows PowerShell with `wsl --shutdown`, noting that this stops every running WSL distribution. Reopen WSL and verify the client, route, and bastion port:

```bash
bhc vpn-status
```

The Windows client requires administrator elevation. Register its fixed signed executable as an on-demand task once:

```bash
bhc vpn-setup
```

Windows displays one UAC prompt during setup. The task uses the current interactive Windows user, stores no password, has no automatic trigger or caller-controlled arguments, and accepts only a validly signed `sslvpn-client.exe` under Windows Program Files. Normal use is then:

```bash
bhc vpn-open
bhc vpn-status
```

`vpn-open` starts the task without another UAC prompt and waits for bastion reachability. If the task is not installed, it falls back to direct Windows elevation. Remove the task with `bhc vpn-setup-remove` when it is no longer wanted. Set `BHC_VPN_CLIENT` only for another protected Windows installation path, and use `BHC_VPN_WAIT_TIMEOUT=0` or `bhc vpn-open --wait 0` to disable waiting.

## Usage

```bash
bhc vpn-setup     # one-time UAC approval for the fixed signed client
bhc vpn-status    # inspect the Windows client, WSL route, and bastion port
bhc vpn-open      # start the Windows client and wait for the route
bhc ssh          # default: login05
bhc ssh -N 1     # login01
bhc ssh -N 5     # login05
bhc sftp
bhc check
bhc check --with-otp
```

Run `vpn-setup` once to register `\BJMU HPC\SafeConnect` as an on-demand Windows task. Setup accepts only a validly signed `sslvpn-client.exe` under Windows Program Files, fixes the task action to that path, uses the current interactive user at the highest run level, and does not store a Windows password. Windows requests UAC approval during setup; later `vpn-open` calls use the task without repeating that prompt. Use `bhc vpn-setup-remove` to remove it.

`vpn-open` does not enter, store, or bypass VPN credentials. Complete VPN authentication in the Windows client when necessary, then use `bhc vpn-status` to verify that `10.100.0.88:22` is reachable. Without the task, `vpn-open` falls back to direct Windows elevation. These commands require Windows interop and are not a replacement Linux VPN implementation.

`-N` specifies the numeric suffix of the asset name, not the gateway menu position. Run long workloads through Slurm rather than directly on a login node.

## Troubleshooting

- If `VPN ready: no`, complete authentication in the Windows client and check that WSL mirrored networking is enabled.
- A timeout or unreachable gateway usually indicates a disconnected BJMU VPN.
- `gopass could not read ...` indicates a missing OTP entry, GPG unlock failure, or invalid OTP data.
- `DEFAULT_PWD is unset` means the current shell has not exported the gateway password.
- Run `bhc check --with-otp` before diagnosing SSH or SFTP prompt handling.

Credentials are kept out of project files and child-process environments, but environment variables remain readable by the current user and its processes. Use the connector only on a trusted workstation.
