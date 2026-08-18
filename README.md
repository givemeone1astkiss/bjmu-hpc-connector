# bjmu-hpc-connector

`bjmu-hpc-connector` provides the `bhc` command for authorized BJMU AI4DD HPC users. It obtains a TOTP from `gopass`, completes gateway authentication, selects a login node, and opens an interactive SSH or SFTP session.

## Requirements

- Linux and Python 3.10+
- BJMU VPN access
- OpenSSH client, `sshpass`, GnuPG 2.x, `gopass`, and `pipx`

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

## Usage

```bash
bhc ssh          # default: login05
bhc ssh -N 1     # login01
bhc ssh -N 5     # login05
bhc sftp
bhc check
bhc check --with-otp
```

`-N` specifies the numeric suffix of the asset name, not the gateway menu position. Run long workloads through Slurm rather than directly on a login node.

## Troubleshooting

- A timeout or unreachable gateway usually indicates a disconnected BJMU VPN.
- `gopass could not read ...` indicates a missing OTP entry, GPG unlock failure, or invalid OTP data.
- `DEFAULT_PWD is unset` means the current shell has not exported the gateway password.
- Run `bhc check --with-otp` before diagnosing SSH or SFTP prompt handling.

Credentials are kept out of project files and child-process environments, but environment variables remain readable by the current user and its processes. Use the connector only on a trusted workstation.
