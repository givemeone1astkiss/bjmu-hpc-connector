# bjmu-hpc-connector

`bjmu-hpc-connector` provides the `bhc` command for the BJMU AI4DD HPC gateway. It retrieves a TOTP from `gopass`, completes the gateway prompts, selects a numbered login node, and preserves an interactive SSH or SFTP terminal.

The connector is intended for authorized BJMU HPC users on Linux. It does not bypass authentication and does not store credentials in this repository.

## Features

- `bhc ssh -N 5` maps node number `5` to `login05` and selects the asset by name.
- `bhc sftp` opens the routed SFTP session and submits the gateway's required `password + OTP` credential.
- `bhc check --with-otp` validates commands, configuration, and OTP retrieval without printing secrets.
- Passwords are removed from child-process environments; the SSH first factor is passed to `sshpass` through an anonymous file descriptor.
- The implementation uses only the Python standard library.

## Requirements

- Linux with Python 3.10 or newer
- OpenSSH client (`ssh` and `sftp`)
- `sshpass`
- GnuPG 2.x with a local secret key
- `gopass`
- Access to the BJMU VPN

### Install system tools

On Ubuntu or Debian, install the general dependencies first:

```bash
sudo apt update
sudo apt install git gnupg openssh-client sshpass pipx curl
```

Do not install the unrelated Debian package that also uses the name `gopass`. Follow the [official gopass setup guide](https://github.com/gopasspw/gopass/blob/master/docs/setup.md) to add its package repository:

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

For other operating systems, use the installation commands maintained by the [official gopass project](https://github.com/gopasspw/gopass#installation).

## Configure gopass and OTP

List existing secret keys or create one:

```bash
gpg --list-secret-keys
gpg --full-generate-key  # only if no suitable secret key exists
```

Initialize the password store:

```bash
gopass setup
```

Create the OTP entry in a protected editor. Paste the `otpauth://totp/...` URI provided by the gateway as a line in the entry, then save and close the editor:

```bash
gopass insert -m otp/aidd
gopass otp -o otp/aidd
```

The last command must print exactly one six-digit token. See the [gopass OTP documentation](https://github.com/gopasspw/gopass/blob/master/docs/features.md#adding-otp-secrets) for accepted entry formats.

Storing an OTP seed beside ordinary passwords reduces factor separation. Use a separate gopass store or hardware-backed GPG key when your security policy requires stronger isolation. Never commit a gopass store or an `otpauth://` URI to this repository.

## Environment variables

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `BHC_USER` | Yes | — | BJMU gateway and cluster username |
| `DEFAULT_PWD` | Yes | — | Static gateway password |
| `BHC_GPG_PASSPHRASE` | No | `DEFAULT_PWD` | Passphrase injected only after an explicit GPG pinentry prompt |
| `BHC_BASTION` | No | `10.100.0.88` | Gateway host or IP |
| `BHC_SFTP_TARGET` | No | `10.100.0.5` | Internal target used by the gateway's routed SFTP username |
| `BHC_OTP_ENTRY` | No | `otp/aidd` | gopass entry containing the TOTP seed |
| `BHC_DEFAULT_NODE` | No | `5` | Default login-node suffix, from `1` to `7` |
| `BHC_NODE_PREFIX` | No | `login` | Asset-name prefix used to construct names such as `login05` |
| `BHC_OTP_TIMEOUT` | No | `20` | Seconds allowed for gopass and pinentry |

Configure non-secret values in your shell startup file:

```bash
export BHC_USER="your_cluster_username"
export BHC_BASTION="10.100.0.88"
export BHC_SFTP_TARGET="10.100.0.5"
export BHC_OTP_ENTRY="otp/aidd"
export BHC_DEFAULT_NODE="5"
```

Prefer entering passwords for the current shell instead of storing them in plaintext startup files:

```bash
read -rsp 'BJMU gateway password: ' DEFAULT_PWD; echo
export DEFAULT_PWD

read -rsp 'GPG passphrase (Enter to reuse gateway password): ' BHC_GPG_PASSPHRASE; echo
export BHC_GPG_PASSPHRASE
```

If `BHC_GPG_PASSPHRASE` is empty, the connector uses `DEFAULT_PWD` when pinentry needs to unlock the OTP entry. Environment variables remain readable by the current user and its processes; use this tool only on a trusted workstation.

The included `.env.example` is a reference only. The connector deliberately does not load `.env` files automatically.

## Install the connector

From the repository root:

```bash
pipx install .
bhc check --with-otp
```

For development:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Usage

```bash
bhc ssh          # defaults to BHC_DEFAULT_NODE, normally login05
bhc ssh -N 1     # login01
bhc ssh -N 5     # login05
bhc sftp
bhc check
bhc check --with-otp
```

`-N` is the numeric suffix of the asset name, not a persistent position in the gateway menu. Long-running computation must be submitted through Slurm rather than run on a login node.

## Troubleshooting

- A timeout or unreachable gateway usually means the BJMU VPN route is unavailable.
- `gopass could not read ...` indicates a missing OTP entry, failed GPG unlock, or invalid TOTP data.
- `DEFAULT_PWD is unset` means the current shell has not exported the static gateway password.
- Use `bhc check --with-otp` before debugging SSH or SFTP prompt handling.

## Security notes

- Secrets are never intentionally printed or written to project files.
- OTP output is accepted only as one exact six-digit line from a successful `gopass otp` process.
- The connector injects a GPG passphrase only after detecting the literal `Passphrase:` pinentry prompt.
- Review prompt patterns after any gateway upgrade; fail closed rather than sending credentials to an unrecognized prompt.

