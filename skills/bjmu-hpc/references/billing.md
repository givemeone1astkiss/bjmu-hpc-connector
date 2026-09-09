# BJMUHPC billing reference

Source: <https://ai4dd.bjmu.edu.cn/account-and-policy/billing-policy.html>

Verified on 2026-09-02. Re-check the official page before changing rates or when
the platform announces a policy update.

## Compute rates

| Partition | Unit | Internal rate | External rate |
|---|---|---:|---:|
| `cn-short` | CPU core-hour | 0.10 CNY | 0.20 CNY |
| `cn-long` | CPU core-hour | 0.10 CNY | 0.20 CNY |
| `fat2way` | CPU core-hour | 0.16 CNY | 0.32 CNY |
| `gpu_l40` | GPU card-hour | 2.90 CNY | 5.80 CNY |
| `gpu_l48` | GPU card-hour | 2.90 CNY | 5.80 CNY |
| `gpu_a800` | GPU card-hour | 12.00 CNY | 24.00 CNY |
| `gpu_h100` | GPU card-hour | 12.00 CNY | 24.00 CNY |

The template defaults to the internal multiplier `1`. Set
`BJMU_BILLING_MULTIPLIER=2` inside a job only when the account is billed as an
external user. Determine the charging class from cluster policy or account
administration rather than guessing from institution text.

## Formula and interpretation

- GPU job: `allocated GPU cards × elapsed seconds / 3600 × internal rate × multiplier`.
- CPU job: `allocated CPU cores × elapsed seconds / 3600 × internal rate × multiplier`.
- GPU-node CPU cores are included in the GPU card-hour category and are not added
  a second time.
- The ledger assigns the complete job to its completion month. Start and end
  timestamps remain available for manual splitting if a job crosses a month.
- The result is an estimate from batch-script wall time and Slurm allocation. The
  platform's accounting records and invoices remain authoritative.

## Ledger schema

Allocation parsing must support both `TRES=` (the current cluster's `scontrol`
output) and `AllocTRES=`. `sacct` exposes `AllocTRES` as a separate export column.
Do not assume `SLURM_GPUS_ON_NODE` is populated for every `--gres` job. Test with
real Slurm output before relying on an environment-only simulation. Preserve
all partition alternatives in the accounting code when changing job directives;
never globally replace partition names throughout a job script.

For historical `NA` rows, export `JobIDRaw,Partition,ElapsedRaw,AllocCPUS,AllocTRES,State`
using `sacct -X -n -P` with explicit dates. Match allocation rows by job ID (exclude
`.batch` and other steps), preserve recorded timer durations and multipliers,
back up the TSV, then reconcile it under the existing lock and regenerate `Sum`.
Submitted jobs retain their original script copies; reconcile those after they
finish even if their source scripts have already been fixed.

`$HOME/bjmu_hpc_billing/YYYY-MM.tsv` uses these columns:

```text
start_time  end_time  elapsed_seconds  elapsed_hours  job_id  array_task_id
job_name  partition  unit_kind  allocated_units  unit_rate_cny_per_hour
multiplier  estimated_cost_cny  exit_code  signal
```

The ledger's last row is a monthly summary. Its first field is `Sum`, its
`estimated_cost_cny` field contains the four-decimal total of all numeric job
costs, and its other fields are empty. `NA` estimates remain visible as job rows
but are excluded from the total. Each job completion regenerates the summary by
removing any existing `Sum`, appending the completed job, and recalculating the
total.

The whole read-modify-write operation is protected by
`$HOME/bjmu_hpc_billing/YYYY-MM.tsv.lock`. The template writes a temporary file in
the same directory and atomically replaces the TSV while holding that lock. Keep
the lock separate from the TSV: locking the TSV inode itself is unsafe when the
ledger is replaced and several jobs finish concurrently.

Never place the shared ledger on `/lustre1`, which is documented without file
locking.
