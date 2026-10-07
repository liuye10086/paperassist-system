import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from contextlib import redirect_stderr
from io import StringIO
from psycopg import Error as PsycopgError

DATABASE_SCRIPTS = Path(__file__).resolve().parents[1] / "database"
sys.path.insert(0, str(DATABASE_SCRIPTS))

from setup_database_roles import main, replace_settings, validate_owner_url, write_private


class SetupConfigurationTests(unittest.TestCase):
    def test_failure_reports_phase_and_safe_sqlstate(self):
        from psycopg.errors import InvalidPassword
        def failing_run(progress):
            progress('admin_authentication')
            raise InvalidPassword('private-secret-marker')
        output = StringIO()
        with patch('setup_database_roles.run', side_effect=failing_run), redirect_stderr(output):
            self.assertEqual(main(), 1)
        self.assertIn('admin_authentication', output.getvalue())
        self.assertIn('28P01', output.getvalue())
        self.assertNotIn('private-secret-marker', output.getvalue())

    def test_raw_driver_failure_is_sanitized(self):
        output = StringIO()
        with patch("setup_database_roles.run", side_effect=PsycopgError("private-secret-marker")), redirect_stderr(output):
            self.assertEqual(main(), 1)
        self.assertNotIn("private-secret-marker", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())

    def test_replace_preserves_unrelated_settings_and_removes_duplicates(self):
        original = "# local\nOPENAI_API_KEY=local-secret\nPAPERASSIST_DATABASE_URL=old\nexport PAPERASSIST_DATABASE_URL=duplicate\nPAPERASSIST_MIGRATION_DATABASE_URL=owner\n"
        result = replace_settings(original, {"PAPERASSIST_DATABASE_URL": "new"}, {"PAPERASSIST_MIGRATION_DATABASE_URL"})
        self.assertEqual(result, "# local\nOPENAI_API_KEY=local-secret\nPAPERASSIST_DATABASE_URL='new'\n")

    def test_atomic_write_replaces_content_and_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text("old", encoding="utf-8")
            write_private(path, "new\n")
            self.assertEqual(path.read_text(encoding="utf-8"), "new\n")
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_accepts_explicit_local_owner(self):
        url = validate_owner_url("postgresql://owner:fake@127.0.0.1:5432/paperassist_system", "paperassist_system")
        self.assertEqual(url.drivername, "postgresql+psycopg")

    def test_rejects_redirects_wrong_database_and_missing_secrets(self):
        for value in (
            None,
            "postgresql://owner:fake@elsewhere/paperassist_system",
            "postgresql://owner:fake@localhost/other",
            "postgresql://owner@localhost/paperassist_system",
            "postgresql://owner:fake@localhost/paperassist_system?host=other",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_owner_url(value, "paperassist_system")


if __name__ == "__main__":
    unittest.main()
