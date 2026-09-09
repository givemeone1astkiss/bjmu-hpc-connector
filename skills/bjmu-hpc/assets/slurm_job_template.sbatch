#!/usr/bin/env bash
#SBATCH --job-name=<experiment_name>
#SBATCH --partition=<compute_partition>
#SBATCH --account=<verified_slurm_account>
#SBATCH --qos=<qos_matching_account_and_partition>
#SBATCH --nodes=<compute_node_count>
#SBATCH --ntasks=<slurm_task_count>
#SBATCH --cpus-per-task=<cpu_threads_per_task>
# For GPU jobs only; remove this line for CPU-only jobs.
#SBATCH --gres=gpu:<gpu_count_per_node>
#SBATCH --time=<wall_time_limit_HH:MM:SS>
#SBATCH --signal=B:TERM@60
#SBATCH --no-requeue
#SBATCH --output=<absolute_lustre_log_dir>/<experiment_name>-%j.out
#SBATCH --error=<absolute_lustre_log_dir>/<experiment_name>-%j.err

# ---- Default accounting prefix: keep in every generated job script. ----
bjmu_bill_started_epoch=$(date +%s)
bjmu_bill_started_iso=$(date --iso-8601=seconds)
bjmu_bill_signal=""

bjmu_record_bill() {
  local application_exit_code=$?
  trap - EXIT TERM INT
  set +e

  local ended_epoch ended_iso elapsed_seconds elapsed_hours
  local job_id array_task_id job_name partition job_line
  local unit_kind allocated_units unit_rate multiplier estimated_cost
  local billing_dir billing_month billing_file billing_lock billing_tmp monthly_total

  ended_epoch=$(date +%s)
  ended_iso=$(date --iso-8601=seconds)
  elapsed_seconds=$((ended_epoch - bjmu_bill_started_epoch))
  elapsed_hours=$(awk -v seconds="$elapsed_seconds" 'BEGIN {printf "%.6f", seconds / 3600}')

  job_id=${SLURM_JOB_ID:-unknown}
  array_task_id=${SLURM_ARRAY_TASK_ID:-}
  job_name=${SLURM_JOB_NAME:-unknown}
  partition=${SLURM_JOB_PARTITION:-unknown}
  multiplier=${BJMU_BILLING_MULTIPLIER:-1}
  unit_kind=unknown
  allocated_units=""
  unit_rate=""

  job_line=$(scontrol show job -o "$job_id" 2>/dev/null || true)
  case "$partition" in
    gpu_l40|gpu_l48|gpu_a800|gpu_h100)
      unit_kind=gpu
      allocated_units=$(printf '%s\n' "$job_line" | sed -nE 's/.*[[:space:]](AllocTRES|TRES)=[^ ]*gres\/gpu=([0-9]+).*/\2/p')
      if [[ ! "$allocated_units" =~ ^[0-9]+$ ]]; then
        if [[ "${SLURM_GPUS_ON_NODE:-}" =~ ^[0-9]+$ && "${SLURM_JOB_NUM_NODES:-}" =~ ^[0-9]+$ ]]; then
          allocated_units=$((SLURM_GPUS_ON_NODE * SLURM_JOB_NUM_NODES))
        else
          allocated_units=""
        fi
      fi
      case "$partition" in
        gpu_l40|gpu_l48) unit_rate=2.9 ;;
        gpu_a800|gpu_h100) unit_rate=12.0 ;;
      esac
      ;;
    cn-short|cn-long|fat2way)
      unit_kind=cpu_core
      allocated_units=$(printf '%s\n' "$job_line" | sed -nE 's/.*NumCPUs=([0-9]+).*/\1/p')
      if [[ ! "$allocated_units" =~ ^[0-9]+$ ]]; then
        if [[ "${SLURM_NTASKS:-}" =~ ^[0-9]+$ && "${SLURM_CPUS_PER_TASK:-}" =~ ^[0-9]+$ ]]; then
          allocated_units=$((SLURM_NTASKS * SLURM_CPUS_PER_TASK))
        else
          allocated_units=""
        fi
      fi
      case "$partition" in
        cn-short|cn-long) unit_rate=0.1 ;;
        fat2way) unit_rate=0.16 ;;
      esac
      ;;
  esac

  if [[ "$allocated_units" =~ ^[0-9]+$ && "$unit_rate" =~ ^[0-9]+([.][0-9]+)?$ && "$multiplier" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    estimated_cost=$(awk -v seconds="$elapsed_seconds" -v units="$allocated_units" \
      -v rate="$unit_rate" -v factor="$multiplier" \
      'BEGIN {printf "%.4f", seconds / 3600 * units * rate * factor}')
  else
    allocated_units=${allocated_units:-NA}
    unit_rate=${unit_rate:-NA}
    estimated_cost=NA
  fi

  job_name=${job_name//$'\t'/ }
  job_name=${job_name//$'\n'/ }
  billing_month=$(date -d "@$ended_epoch" +%Y-%m)
  billing_dir="$HOME/bjmu_hpc_billing"
  billing_file="$billing_dir/$billing_month.tsv"
  billing_lock="$billing_file.lock"
  (
  set -e
  mkdir -p "$billing_dir"

  # Lock a separate, stable inode so the ledger can be atomically replaced.
  exec 9>>"$billing_lock"
  flock -x 9
  billing_tmp=$(mktemp "$billing_dir/.${billing_month}.XXXXXX")
  if [[ -s "$billing_file" ]]; then
    awk -F '\t' 'NR == 1 || $1 != "Sum"' "$billing_file" >"$billing_tmp"
  else
    printf 'start_time\tend_time\telapsed_seconds\telapsed_hours\tjob_id\tarray_task_id\tjob_name\tpartition\tunit_kind\tallocated_units\tunit_rate_cny_per_hour\tmultiplier\testimated_cost_cny\texit_code\tsignal\n' >"$billing_tmp"
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$bjmu_bill_started_iso" "$ended_iso" "$elapsed_seconds" "$elapsed_hours" \
    "$job_id" "$array_task_id" "$job_name" "$partition" "$unit_kind" \
    "$allocated_units" "$unit_rate" "$multiplier" "$estimated_cost" \
    "$application_exit_code" "${bjmu_bill_signal:-none}" >>"$billing_tmp"
  monthly_total=$(awk -F '\t' \
    'NR > 1 && $1 != "Sum" && $13 ~ /^[0-9]+([.][0-9]+)?$/ {total += $13} END {printf "%.4f", total + 0}' \
    "$billing_tmp")
  printf 'Sum\t\t\t\t\t\t\t\t\t\t\t\t%s\t\t\n' "$monthly_total" >>"$billing_tmp"
  chmod 600 "$billing_tmp"
  mv -f "$billing_tmp" "$billing_file"
  flock -u 9
  exec 9>&-
  ) || echo "WARNING: billing update failed for job $job_id; reconcile with sacct" >&2

  exit "$application_exit_code"
}

bjmu_handle_signal() {
  bjmu_bill_signal=$1
  exit "$2"
}

trap bjmu_record_bill EXIT
trap 'bjmu_handle_signal TERM 143' TERM
trap 'bjmu_handle_signal INT 130' INT
# ---- End accounting prefix. ----

project_root="<absolute_lustre_project_root>"
source /appsnew/source/Anaconda3-2025.06-1.sh
conda activate "<verified_conda_environment>"
set -euo pipefail

cd "$project_root"
export PYTHONPATH="$project_root:${PYTHONPATH:-}"
echo "host=$(hostname) date=$(date --iso-8601=seconds) job_id=${SLURM_JOB_ID:-unknown}"
python -c 'import torch; print(torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0))'

# Replace this function body with the exact command, including explicit config,
# seed, and resume policy. Its exit status is preserved by the billing trap.
run_application() {
  echo "ERROR: replace run_application in the Slurm template before submission" >&2
  return 2
}

run_application
# ---- The EXIT trap above is the default accounting suffix. ----
