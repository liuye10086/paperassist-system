"""Disk-backed sorted gene comparison, with bounded SQLite page cache."""
from collections import Counter
import csv
import json
import sqlite3

from .bulk_results import BULK_DIRECTIONS, bulk_row_class, finite_metric


def _load(db, name, path, selection, labels):
    from .bulk_sensitivity import _TABLE_COLUMNS
    db.execute(f'CREATE TABLE {name} (feature TEXT PRIMARY KEY, category TEXT, q REAL, effect REAL, symbol TEXT) WITHOUT ROWID')
    count = 0
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t', strict=True)
        fields = reader.fieldnames or []
        if not _TABLE_COLUMNS.issubset(fields) or len(fields) != len(set(fields)):
            raise ValueError('bulk_comparison_columns_invalid')
        for row in reader:
            if row['contrast_id'] != selection.contrast_id:
                continue
            if (None in row or None in row.values() or not row['feature_id'] or not row['row_key']
                    or (row['numerator'], row['denominator']) != labels
                    or row['test_status'] not in ('tested', 'excluded', 'not_computable')):
                raise ValueError('bulk_comparison_row_invalid')
            category = bulk_row_class(row, selection)
            if category in BULK_DIRECTIONS and selection.direction not in ('both', category):
                category = 'direction_not_selected'
            q = finite_metric(row[selection.q_column])
            q = q if q is not None and 0 <= q <= 1 else None
            try:
                db.execute(f'INSERT INTO {name} VALUES (?,?,?,?,?)',
                           (row['feature_id'], category, q, finite_metric(row['effect_value']), row['symbol']))
            except sqlite3.IntegrityError as exc:
                raise ValueError('bulk_comparison_row_invalid') from exc
            count += 1
    if not count:
        raise ValueError('bulk_comparison_rows_missing')


def compare_index(index, baseline_path, scenario_path, baseline, scenario, labels, *,
                  page=1, page_size=100, change_stream=None):
    from .bulk_sensitivity import _CHANGE_CLASSES, _GENE_FIELDS, _change
    exists = index.exists()
    db = sqlite3.connect(index)
    try:
        db.execute('PRAGMA cache_size=-2048')
        db.execute('PRAGMA temp_store=FILE')
        if not exists:
            _load(db, 'before', baseline_path, baseline, labels)
            _load(db, 'after', scenario_path, scenario, labels)
            db.execute('CREATE TABLE changes (ordinal INTEGER PRIMARY KEY, item TEXT)')
            counts = dict.fromkeys(_CHANGE_CLASSES, 0)
            left_counts, right_counts = Counter(), Counter()
            rows = db.execute('''SELECT ids.feature, b.category,b.q,b.effect,b.symbol,a.category,a.q,a.effect,a.symbol
                FROM (SELECT feature FROM before UNION SELECT feature FROM after) ids
                LEFT JOIN before b ON b.feature=ids.feature LEFT JOIN after a ON a.feature=ids.feature ORDER BY ids.feature''')
            total = 0
            for feature, lc, lq, le, ls, rc, rq, re, rs in rows:
                lc, rc = lc or 'absent', rc or 'absent'
                change = _change(lc, rc)
                counts[change] += 1
                left_counts[lc] += 1
                right_counts[rc] += 1
                item = dict(feature_id=feature, symbol=ls or rs or '', baseline_class=lc, scenario_class=rc,
                            change=change, baseline_q=lq, scenario_q=rq, baseline_effect=le, scenario_effect=re)
                db.execute('INSERT INTO changes VALUES (?,?)', (total, json.dumps(item)))
                total += 1
            result = dict(counts=counts, baseline_counts=dict(left_counts), scenario_counts=dict(right_counts), total=total)
            db.execute('CREATE TABLE summary (value TEXT)')
            db.execute('INSERT INTO summary VALUES (?)', (json.dumps(result),))
            db.execute('DROP TABLE before')
            db.execute('DROP TABLE after')
            db.commit()
        result = json.loads(db.execute('SELECT value FROM summary').fetchone()[0])
        items = [json.loads(row[0]) for row in db.execute('SELECT item FROM changes WHERE ordinal>=? AND ordinal<? ORDER BY ordinal',
                                                        ((page - 1) * page_size, page * page_size))]
        if change_stream is not None:
            writer = csv.DictWriter(change_stream, fieldnames=_GENE_FIELDS, delimiter='\t', lineterminator='\n')
            writer.writeheader()
            for row in db.execute('SELECT item FROM changes ORDER BY ordinal'):
                writer.writerow(json.loads(row[0]))
        return dict(result, items=items, page=page, page_size=page_size)
    finally:
        db.close()
