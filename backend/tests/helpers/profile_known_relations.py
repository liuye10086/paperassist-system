"""Deterministic input and hand-written oracle; no ProfileScan dependency."""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from io import BytesIO
import argparse
import json
from pathlib import Path
from time import perf_counter
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree

from openpyxl import Workbook


def sample_rows():
    rows = [[x, 3*x+7, 100-2*x, 5, f'2026-01-{x:02d}'] for x in range(1, 21)]
    return rows + [rows[5].copy(), rows[5].copy(), [100, 307, -100, 5, '2026-01-24'],
                   [None, None, None, 5, '2026-02-30'], [21, 70, 58, 5, '01/02/2026']]


def workbook_bytes() -> bytes:
    book = Workbook()
    book.active.title = '已知关系'
    book.properties.created = book.properties.modified = datetime(2026, 1, 1)
    book.active.append(['合成X', '同向Y', '反向Z', '固定值', '日期文本'])
    for row in sample_rows():
        book.active.append(row)
    raw = BytesIO()
    book.save(raw)
    book.close()
    # Freeze archive metadata as well as workbook properties for byte reproducibility.
    output = BytesIO()
    with ZipFile(raw) as source, ZipFile(output, 'w', ZIP_DEFLATED) as target:
        for name in sorted(source.namelist()):
            from zipfile import ZipInfo
            info = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            data = source.read(name)
            if name == 'docProps/core.xml':
                root = ElementTree.fromstring(data)
                for node in root:
                    if node.tag.endswith('}modified'):
                        node.text = '2026-01-01T00:00:00Z'
                data = ElementTree.tostring(root, encoding='utf-8')
            target.writestr(info, data)
    return output.getvalue()


_EXPECTED = {
    'sheet': '已知关系', 'data_range': 'A2:E26', 'record_count': 25, 'blank_row_count': 0,
    'duplicate_groups': 1, 'duplicate_rows': 3, 'duplicate_extra_rows': 2,
    'duplicate_coordinates': [7, 22, 23], 'paired_count': 24,
    'numeric': [
        {'n': 24, 'mean': 343/24, 'q1': 6, 'q3': 16.25, 'iqr': 10.25, 'lower_fence': '-9.375', 'upper_fence': '31.625', 'outlier_count': 1},
        {'n': 24, 'mean': 49.875, 'q1': 25, 'q3': 55.75, 'iqr': 30.75, 'lower_fence': '-21.125', 'upper_fence': '101.875', 'outlier_count': 1},
        {'n': 24, 'mean': 100-2*343/24, 'q1': 67.5, 'q3': 88, 'iqr': 20.5, 'lower_fence': '36.75', 'upper_fence': '118.75', 'outlier_count': 1},
        {'n': 25, 'mean': 5, 'q1': 5, 'q3': 5, 'iqr': 0, 'lower_fence': '5', 'upper_fence': '5', 'outlier_count': 0}],
    'time_candidates': {'valid_count': 23, 'invalid_count': 1, 'ambiguous_count': 1},
    'missing': ['A25', 'B25', 'C25'], 'outliers': ['A24', 'B24', 'C24'],
    'time_invalid': ['E25'], 'time_ambiguous': ['E26'],
}


def expected_profile() -> dict:
    return deepcopy(_EXPECTED)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', required=True)
    destination = Path(parser.parse_args().output_dir)
    if not destination.is_absolute():
        parser.error('--output-dir must be absolute')
    content = workbook_bytes()
    from app.adapters.excel_structure import extract_excel_structure
    from app.core.config import ExcelSettings
    started = perf_counter()
    extract_excel_structure(content, 'known-relations.xlsx', ExcelSettings())
    seconds = perf_counter() - started
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'known-relations.xlsx').write_bytes(content)
    manifest = {'filename': 'known-relations.xlsx', 'size_bytes': len(content), 'sha256': sha256(content).hexdigest(),
                'structure_parse_seconds': seconds, 'expected': expected_profile()}
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (destination / '验收说明.txt').write_text(
        '唯一工作表：已知关系；数据范围A2:E26，共25记录。\n'
        '生成定义：24条有效成对记录逐行Y=3X+7、Z=100−2X；这不是产品自动识别相关关系的结果。\n'
        '第7/22/23行属于一个完整重复组；A24/B24/C24为IQR异常候选，但仍满足定义关系，不等于错误。\n'
        'A25/B25/C25缺失；固定值列25个5，无异常，常量相关系数无定义，不声明零相关。\n'
        '日期文本23个有效候选；E25无效，E26歧义；保持文本。原始单位未确认。\n'
        '上传后保存原始数据版本，打开概况，查看重复、缺失、异常、日期问题并定位到上述坐标；跨20行查看原始记录。\n'
        '核对描述统计结果仍可读、原件与数据集可下载；不自动删行，不输出相关系数、P值或因果结论。\n'
        'manifest中的耗时仅为本机小样本真实结构解析，不代表Worker吞吐或配置上限性能。\n', encoding='utf-8')
    print(json.dumps({k: manifest[k] for k in ('size_bytes', 'sha256', 'structure_parse_seconds')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
