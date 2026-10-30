import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('local_notices', ROOT / 'script/notices/collect_local.py')
notices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notices)


class NoticePathTests(unittest.TestCase):
    def test_embedded_notice_file_names(self):
        for path in ['statsmodels/multivariate/factor_rotation/COPYRIGHTS.txt',
                     'typescript/ThirdPartyNoticeText.txt',
                     'lz-string/tests/lib/jasmine-1.3.1/MIT.LICENSE',
                     'openpyxl.dist-info/LICENCE.rst',
                     'pypdfium2.dist-info/licenses/data/linux_x64/BUILD_LICENSES/icu.txt']:
            with self.subTest(path=path):
                self.assertTrue(notices.notice_path(path))

    def test_code_modules_are_not_notice_texts(self):
        for path in ['packaging/licenses/__init__.py', 'packaging/licenses/_spdx.py', 'app/license.js', 'LICENSE.dll']:
            with self.subTest(path=path):
                self.assertFalse(notices.notice_path(path))
