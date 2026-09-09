---
name: bjmu-hpc
description: Connect to and operate the Peking University AI4DD BJMUHPC cluster through its VPN and bastion host. Use for automated bhc SSH or SFTP access, project upload, Conda setup, Lustre storage selection, metered Slurm GPU/CPU submission, job monitoring, log retrieval, and diagnosing VPN, queue, environment, storage, or billing-record failures.
---

# BJMU HPC

Operate BJMUHPC safely from the local workstation. Keep authentication interactive and keep all credentials out of repositories, command output, logs, and final responses.

## Connection configuration

- Connector: `bhc`, installed from the `bjmu-hpc-connector` package.
- Load the username, bastion, routed SFTP target, and OTP entry from `BHC_USER`, `BHC_BASTION`, `BHC_SFTP_TARGET`, and `BHC_OTP_ENTRY`; never hardcode personal values in a repository.
- Read the static password, when the current protocol requires it, only from the local `DEFAULT_PWD` environment variable.
- Retrieve the current TOTP with `gopass otp -o "$BHC_OTP_ENTRY"`; never print or persist the result.
- Supported VPN client: SafeConnect/DPtech SSL VPN 10.1.14.0 on Windows, normally at `C:\Program Files (x86)\SafeConnect\SSLVPN Client\sslvpn-client.exe`.
- WSL networking: WSL 2 mirrored mode passes the Windows VPN route into WSL; do not install an unverified Linux replacement client.

Do not depend on the legacy `sshpc` or `sftpc` aliases. The connector invokes `sshpass`, `ssh`, and `sftp` directly.

## Establish and diagnose the VPN

### Network execution boundary

Do not run cluster connectivity commands in a restricted filesystem/network sandbox. A sandbox can hide the Windows VPN process and its injected WSL route, causing a false disconnected result even when the normal WSL session can reach the cluster.

- Run `bhc vpn-status`, `bhc vpn-open`, `bhc check`, `bhc ssh`, `bhc sftp`, and direct bastion reachability checks with network access outside the restricted sandbox.
- Filesystem-only inspection of the skill or project files may remain sandboxed.
- Never report the VPN as down from a sandboxed negative result. Repeat the check with real network access before asking the user to reconnect.
- An already-open SSH PTY may survive while a new sandboxed connection appears to fail; this does not prove that SFTP or fresh authentication is unavailable.

Run the read-only diagnostic before retrying credentials when the bastion is unavailable:

```bash
bhc vpn-status
```

It reports the WSL environment, Windows `sslvpn-client` process, route to the configured bastion, and TCP reachability of port 22. It does not read `DEFAULT_PWD`, `BHC_USER`, or the OTP. Treat `VPN ready: yes` as the connection prerequisite for SSH/SFTP.

When the route is absent, start the supported Windows client from WSL:

```bash
bhc vpn-open
bhc vpn-open --wait 0  # start/check without waiting
```

The vendor client embeds `requireAdministrator`. To avoid repeated UAC prompts without weakening UAC, register a fixed on-demand Task Scheduler action once:

```bash
bhc vpn-setup
```

This is an external Windows configuration change and requires explicit user authorization plus one UAC approval. Setup accepts only a validly signed `sslvpn-client.exe` under Windows Program Files and creates `\BJMU HPC\SafeConnect` for the current interactive user with `RunLevel=Highest`, no trigger, no stored Windows password, and no caller-controlled arguments. Do not register arbitrary paths or commands. Remove it only with explicit authorization:

```bash
bhc vpn-setup-remove
```

When the task exists, `vpn-open` invokes it with `schtasks.exe /Run`; otherwise it falls back to direct Windows elevation. It waits up to 60 seconds by default and never fills, stores, or bypasses VPN credentials. If the client is already running, do not start a duplicate. `BHC_VPN_CLIENT` may override the executable path for an alternative protected installation, and `BHC_VPN_WAIT_TIMEOUT` may override the wait. These commands require WSL with Windows interop; they are not a native Linux VPN implementation.

If `vpn-status` reports the client running but the bastion unreachable, ask the user to complete or restore the Windows VPN session. It also reports whether the pre-authorized task is installed. If the route is present but the port is unreachable, report the distinction before attempting credentials. Never modify `.wslconfig`, restart WSL, install a replacement VPN package, or terminate the Windows client unless the user explicitly authorizes it.

## Authenticate

1. Run `bhc vpn-status`. If it reports ready, attempt the connection without asking for confirmation. If it is not ready, use `bhc vpn-open` or ask the user to finish the Windows login.
2. Prefer the installed connector in a real TTY. It reloads the interactive Bash environment, reads the OTP from `gopass`, unlocks pinentry from `DEFAULT_PWD` only after detecting the explicit `Passphrase:` prompt, and keeps all credentials out of output:

   ```bash
   bhc check --with-otp
   bhc ssh                 # defaults to login05
   bhc ssh -N 1            # login01 for normal submission work
   ```

   Pass a node suffix from `1` to `7` with `-N` or `--node`; for example, `-N 5` maps to the asset name `login05`. This value is not the bastion's displayed menu position. The default is `5`. Use `login05` only for authorized short GPU tests. The connector requires local GPG access and network access, which may require execution outside a filesystem/network sandbox.
3. If the connector is unavailable, use the direct manual fallback in an interactive Bash TTY:

   ```bash
   SSHPASS="$DEFAULT_PWD" sshpass -e ssh "$BHC_USER@$BHC_BASTION"
   ```

   Read the OTP without displaying it, wait for the second-password prompt, send only the OTP, and then select the target asset by name and IP.
4. Prefer `login01` for normal shell access and Slurm submission. Do not rely forever on a numeric menu position because the asset list can change.
5. If the connection times out, the route is unreachable, or the bastion unexpectedly closes the connection, report that the VPN may be disconnected and ask the user to restore it. Avoid repeated credential attempts when the network path is absent.

The connector separates `gopass` stdout from the pinentry terminal and accepts an OTP only from an output line containing exactly six digits after a successful process exit. It never logs authentication data. For any manual orchestration, retrieve the OTP inside the tool call and redact accidental numeric OTP output. If GPG pinentry asks to unlock `gopass`, first wait until the terminal output explicitly contains `Passphrase:`; only then read `DEFAULT_PWD` and send it directly to pinentry. Never send `DEFAULT_PWD` speculatively, extract a six-digit substring from arbitrary output, or persist any credential. If `DEFAULT_PWD` is unset, ask the user to export it.

## Choose a login node

- `login01` or `login02`: normal command-line access and Slurm submission.
- `login03`: GPU-aware compilation and short interactive debugging; it has one L40S.
- `login04`: general submission/virtualized login node.
- `login05`: graphical/interactive GPU node with 4 L40 GPUs; use it for short CUDA, compilation, inference, and GPU smoke tests.
- `login06`–`login07`: graphical and CPU-interactive specialist nodes.

Never run long training or production computation on a login node. Submit it to Slurm. Keep `login05` GPU checks short and release resources immediately after validation; the platform prohibits long-running jobs on `login05`–`login07`.

## Transfer files with SFTP

Prefer the connector:

```bash
bhc sftp
```

The connector always sends `<DEFAULT_PWD> <current-otp>` on one line at the protected SFTP password prompt, matching the current gateway protocol.

As a manual fallback, use the bastion routing username format:

```bash
sftp "$BHC_USER/$BHC_SFTP_TARGET/$BHC_USER@$BHC_BASTION"
```

Useful SFTP commands are `pwd`, `lpwd`, `cd`, `lcd`, `put`, `get`, and `bye`.

- Upload project code and compute data under the user's `lustre1` tree, not into the small home/configuration area.
- Verify both local and remote paths before `put` or `get`.
- Do not overwrite checkpoints, logs, datasets, or remote source trees unless the user's request clearly authorizes it.
- Prefer a timestamped or project-specific remote directory for a new migration.

## Use storage correctly

- `lustre1`: high-throughput working storage for code, datasets, caches, checkpoints, logs, and active computation. Platform quota is user-specific; check it before a large transfer.
- `lustre2`: backup/archive storage, not the primary training work directory.
- `/appsnew`: centrally installed software and environment scripts; do not treat it as project storage.
- `/tmp` and `/ram/tmp`: node-local temporary space and vulnerable to exhaustion. For large temporary files, set a job-specific directory under Lustre:

  ```bash
  export TMPDIR=/lustre1/tmp/$USER/$SLURM_JOB_ID
  mkdir -p "$TMPDIR"
  ```

Clean a job's own temporary directory only after its outputs are safely written. Never recursively delete a broad or unresolved path.

## Configure software environments

Load centrally installed software through `/appsnew/source/` scripts. For Conda, a current entry point is:

```bash
source /appsnew/source/Anaconda3-2025.06-1.sh
```

- Never install into or modify the shared `base` environment.
- Inspect `conda env list` and validate Python, PyTorch, CUDA, PyTorch Lightning, Hydra, TensorBoard, RDKit, and project-specific packages before submission.
- Create or clone a personal environment only when needed and authorized. Do not assume a similarly named environment matches the local workstation.
- Put environment activation in the Slurm script. Do not stack multiple unrelated `source` commands in `.bashrc`.
- Record an environment export or package/version report with the run for reproducibility.

## Inspect resources before submitting

Run read-only checks on a submission node:

```bash
sinfo
squeue -u "$USER"
conda env list
```

Available GPU partitions documented by the platform are:

- `gpu_l40`: up to 4 L40 GPUs per node, 48 GB each.
- `gpu_l48`: up to 8 L40S GPUs per node, 48 GB each.
- `gpu_a800`: up to 8 A800 GPUs per node, 80 GB each.
- `gpu_h100`: up to 8 H100 GPUs per node, 80 GB each.

Single-node jobs may request only the GPUs they need. Multi-node GPU jobs are allocated in whole-node groups of 4 or 8 GPUs. Prefer a single GPU for smoke tests and scale only after correctness and memory use are established.

The platform documentation contains example Slurm accounts and QoS values that are not universal. Before the first real submission, determine the user's actual account/QoS from current associations or user-owned examples. Never copy an example identity blindly.

## Submit reproducible jobs

### Resolve account and QoS from live associations

Slurm accounts and QoS values are user- and partition-specific. Determine the active mapping from live `sacctmgr` associations, administrator guidance, or a recently completed user-owned job. Do not substitute a Unix group for `--account`, guess a QoS from a partition name, or publish account-specific mappings in a reusable Skill.

After an invalid-account or invalid-QoS error, re-check the account/partition/QoS tuple before retrying. Treat every GPU partition as an available platform choice rather than a default or ranking; select it from model memory, precision, throughput, queue state, and experiment urgency.

### GPU job-file parameter semantics and placeholder form

Resolve every resource directive from the workload and current cluster state:

| Directive | Meaning | Selection rule |
|---|---|---|
| `--job-name` | Short queue/log identifier | Use a concise experiment-specific name. |
| `--partition` | Hardware/queue platform | Choose from live GPU partitions after checking `sinfo`; it is not a generic GPU flag. |
| `--account` | Slurm allocation charged by the job | Use the live verified project account. |
| `--qos` | Limits and priority policy | Must match the chosen account and partition according to live associations. |
| `--nodes` | Number of compute nodes | Use one unless the workload intentionally implements multi-node distributed execution. |
| `--ntasks` | Number of Slurm-launched processes | Distinguish a single `torchrun` launcher from one task per rank; match the actual launch command. |
| `--cpus-per-task` | CPU threads allocated to each task | Size from DataLoader workers, preprocessing, and chemistry work; do not copy a fixed value. |
| `--gres=gpu:<N>` | GPUs allocated per node | Request only the GPUs actually consumed by the program and distributed strategy. |
| `--time` | Hard wall-time limit | Estimate from smoke-test throughput plus validation/checkpoint margin; it is not expected runtime. |
| `--no-requeue` | Disable automatic restart | Keep unless requeue/resume semantics were deliberately implemented and tested. |
| `--output` / `--error` | Slurm stdout/stderr destinations | Use separate absolute Lustre paths; `%j` is job ID and `%A_%a` is array job/task. |
| `--array` | Optional indexed task set | Use only for independent configurations with an explicit index-to-config mapping. |

Use a project-owned `.sbatch` file based on
[`assets/slurm_job_template.sbatch`](assets/slurm_job_template.sbatch). The
template is intentionally not directly submittable: replace every
angle-bracketed value from experiment requirements and live cluster state. It
contains mandatory default accounting prefix/suffix logic; preserve that logic
when generating project-specific job files.

Create the absolute log directory before submission. Keep `source` and `conda activate` before `set -u`: activation scripts may read unset variables, and enabling nounset first can terminate the job before the application starts. For arrays use `%A_%a` in log names and preserve the exact task-to-configuration mapping. If an array task exits immediately with empty logs and no `GRES_IDX`, retry a single non-array job from a known-good template before diagnosing the model or Python code.

Prefer a project-owned script such as `scripts/slurm/<experiment>.sbatch` over an ad hoc login-node command. Include:

- explicit job name, partition, node/GPU/CPU/memory/time requests;
- verified account and QoS;
- separate `%j` stdout and stderr paths under a run/log directory;
- `--no-requeue` unless recovery behavior was intentionally designed;
- working-directory change, environment loading, and `conda activate`;
- `TMPDIR` setup when the workload writes large temporary files;
- the exact Hydra configuration/overrides, random seed, and resume checkpoint;
- startup diagnostics such as hostname, date, Python/PyTorch/CUDA versions, and visible GPUs.

### Mandatory job timer and monthly cost ledger

Every newly generated Slurm script must retain the accounting prefix and EXIT /
signal traps from the bundled template. They start timing when the batch script
begins and record one tab-separated job row at termination in:

```text
$HOME/bjmu_hpc_billing/YYYY-MM.tsv
```

The completion month selects the file. The final row is always `Sum`, with the
sum of all numeric estimates in the `estimated_cost_cny` column. At every job
completion, the template removes the previous summary, appends the completed job,
recalculates the total, and writes a new summary. `NA` costs remain visible but
are excluded from the total.

The complete read-modify-write transaction uses a separate stable
`YYYY-MM.tsv.lock` file and atomic replacement. Keep the ledger under `/home`,
which supports `flock`, rather than `/lustre1`.

GPU estimates use allocated cards × elapsed hours × card-hour rate. CPU estimates
use allocated cores × elapsed hours × core-hour rate. Prefer Slurm allocation
data and use environment variables only as a fallback; write `NA` for unknown
partitions or unparsable allocations instead of guessing. Preserve the original
application exit code even if ledger creation fails.

When generating scripts, support both `TRES=` and `AllocTRES=` from `scontrol`;
`SLURM_GPUS_ON_NODE` may be unset for `--gres` jobs. Change partition directives
without globally replacing names in the accounting code, preserving GPU and CPU
rate mappings. After the first job finishes with a new template, compare its
recorded resource count and cost with Slurm allocations and check that the single
final `Sum` equals all numeric job costs. Treat unexpected `NA` as an accounting
failure requiring investigation before reusing the template.

Keep `#SBATCH --signal=B:TERM@60` for a best-effort record near a time limit.
Uncatchable termination, node failure, or a filesystem outage may still require
later reconciliation from `sacct`. Read [the billing reference](references/billing.md)
before changing rates, formulas, schema, or charging class.

Use `sbatch` only after validating paths and configuration. A short `bjmurun-*` smoke test is acceptable for resource verification, but preserve a reviewed Slurm script for real experiments.

## Monitor and recover

Use read-only status checks first:

```bash
squeue -u "$USER"
sacct -j <job-id> --format=JobID,JobName,Partition,State,Elapsed,ExitCode
tail -n 100 <stdout-or-stderr-log>
```

After every GPU submission, once `squeue` reports `R` and the application has had enough time to initialize, verify the assigned compute node with:

```bash
gpuinfo <compute-hostname>
```

`gpuinfo` requires a compute hostname; it does not have a conventional `--help` mode. Map the job to the node and its allocated device indices with `squeue` and `scontrol show job -dd <job-id>` (`GRES_IDX=gpu(IDX:...)`) before interpreting node-wide output. Confirm that the expected number of CUDA processes appears on those indices, memory allocation is nonzero, and utilization is plausible for the current phase. Repeat after a short interval when one sample could coincide with initialization, validation, checkpointing, or CPU preprocessing.

Correlate Slurm state with `gpuinfo`, log timestamps, checkpoint timestamps, TensorBoard event files, and metric progression. Slurm allocation and physical use are distinct: a GPU can be allocated while `gpuinfo` shows zero memory and no process. Repeated zero-memory samples on allocated indices indicate that the job is not currently using CUDA; inspect its job steps and logs for a stalled wrapper, CPU-only phase, failed launch, or wait condition. Conversely, low memory use is not itself a fault when compute utilization and throughput are high. Treat a missing queue entry as ambiguous until `sacct` and logs show whether it completed or failed.

- `PD`: inspect pending reason, partition, requested resources, account, and QoS.
- `OUT_OF_MEMORY`: inspect CPU versus GPU OOM and adjust the corresponding memory or batch configuration.
- `No space left on device`: inspect `TMPDIR` and storage quota; move temporary work to the job-specific Lustre directory.
- `R` but no CUDA process on allocated GPUs: check `GRES_IDX`, sample `gpuinfo` again, then inspect job steps and logs before deciding whether the job is stalled.
- Network loss does not imply the batch job stopped. Reconnect after VPN recovery and query Slurm before taking action.
- Cancel a job only when the user requests it or when cancellation is an explicit part of an authorized experimental decision rule.

## Handoff record

After any submission, report the remote project directory, environment, job ID,
partition/GPU or CPU allocation, log paths, configuration, checkpoint/resume
policy, monthly ledger path, applicable unit rate, and next check criterion. Never
report passwords or OTP values.

## Authoritative guide

When platform behavior appears to have changed, re-read `https://ai4dd.bjmu.edu.cn/`, especially the cluster login, cluster information, quick job commands, GPU submission, software, and FAQ pages. Treat live `sinfo`, account associations, and administrator messages as authoritative for current availability.
