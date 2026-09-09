"""Reconcile existing monthly rows with a saved sacct allocation export."""
import csv
import fcntl
import os
from pathlib import Path
import shutil
import sys
import tempfile
from datetime import datetime
from decimal import Decimal

ledger, export = map(Path, sys.argv[1:3])
rates = {'gpu_l40': '2.9', 'gpu_l48': '2.9', 'gpu_a800': '12',
         'gpu_h100': '12', 'cn-short': '0.1', 'cn-long': '0.1', 'fat2way': '0.16'}
allocations = {}
for row in csv.reader(export.open(), delimiter='|'):
    if len(row) >= 5 and row[0].strip().isdigit():
        allocations[row[0].strip()] = row
with open(str(ledger) + '.lock', 'a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    rows = list(csv.reader(ledger.open(), delimiter='\t'))
    header = rows[0]
    assert len(header) == 15 and header[12] == 'estimated_cost_cny'
    backup = str(ledger) + '.backup-' + datetime.now().strftime('%Y%m%dT%H%M%S%f')
    shutil.copy2(ledger, backup)
    output = [header]
    changed = 0
    unresolved = []
    total = Decimal(0)
    for row in rows[1:]:
        if row[0] == 'Sum':
            continue
        assert len(row) == 15, row
        original = row.copy()
        a = allocations.get(row[4])
        if a:
            partition = a[1]
            tres = dict(x.split('=', 1) for x in a[4].split(',') if '=' in x)
            units = tres.get('gres/gpu') if partition.startswith('gpu_') else a[3]
            if units and units.isdigit() and int(units) > 0 and partition in rates:
                row[7:12] = [partition, 'gpu' if partition.startswith('gpu_') else 'cpu_core', units, rates[partition], row[11]]
                # Keep the original timer duration and multiplier for consistent billing.
                cost = Decimal(row[2]) / 3600 * int(units) * Decimal(row[10]) * Decimal(row[11])
                row[12] = format(cost.quantize(Decimal('0.0001')), 'f')
        if row[12] == 'NA':
            unresolved.append(row[4])
        else:
            total += Decimal(row[12])
        changed += row != original
        output.append(row)
    output.append(['Sum'] + [''] * 11 + [format(total, '.4f'), '', ''])
    fd, tmp = tempfile.mkstemp(prefix='.reconcile-', dir=ledger.parent)
    with os.fdopen(fd, 'w') as f:
        csv.writer(f, delimiter='\t', lineterminator='\n').writerows(output)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, ledger)
    print('backup:', backup)
    print('rows:', len(output)-2, 'changed:', changed, 'sum:', total, 'unresolved:', unresolved)
