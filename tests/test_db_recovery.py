import contextlib
import io
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.db_shard import _cmd_reassemble, _cmd_shard
from src.data.crypto_box import derive_new_password
from src.data.schema import SCHEMA_SQL
from src.data.sharder import load_index, shard_database


class PasswordRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.db'
        with contextlib.closing(sqlite3.connect(self.source)) as conn:
            conn.executescript(SCHEMA_SQL)
            conn.execute("INSERT INTO courses VALUES ('123', 'Test course', 'Teacher')")
            conn.execute("INSERT INTO lectures (sub_id, course_id, summary, emailed_at) "
                         "VALUES ('456', '123', 'Saved summary', '2026-10-14')")
            conn.commit()
        self.shards = self.root / 'sharded'
        self.shards.mkdir()
        self.index = shard_database(str(self.source), str(self.shards),
                                   derive_new_password('student', 'old-password'))
        self.output = self.root / 'recovered.db'
        self.env = patch.dict(os.environ, {
            'STUID': 'student', 'UISPSW': 'new-password',
            'PREVIOUS_UISPSW': 'old-password',
            'GITHUB_OUTPUT': str(self.root / 'step-output'),
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def recover(self):
        with contextlib.redirect_stdout(io.StringIO()):
            _cmd_reassemble(str(self.shards), str(self.output))

    def assert_records_preserved(self):
        with contextlib.closing(sqlite3.connect(self.output)) as conn:
            self.assertEqual(conn.execute('SELECT summary, emailed_at FROM lectures').fetchall(),
                             [('Saved summary', '2026-10-14')])

    def test_rotation_preserves_history_and_writes_only_current_key(self):
        self.recover()
        self.assert_records_preserved()
        self.assertIn('db_key_version=previous', (self.root / 'step-output').read_text())
        migrated = self.root / 'migrated'
        with contextlib.redirect_stdout(io.StringIO()):
            _cmd_shard(str(self.output), str(migrated))
        load_index(str(migrated / 'icourse-index.enc'),
                   derive_new_password('student', 'new-password'))
        with self.assertRaises(ValueError):
            load_index(str(migrated / 'icourse-index.enc'),
                       derive_new_password('student', 'old-password'))
        self.shards = migrated
        os.environ['PREVIOUS_UISPSW'] = ''
        self.recover()
        self.assert_records_preserved()

    def test_current_key_works_without_previous_secret(self):
        os.environ.update(UISPSW='old-password', PREVIOUS_UISPSW='')
        self.recover()
        self.assert_records_preserved()
        self.assertIn('db_key_version=current', (self.root / 'step-output').read_text())

    def test_missing_previous_key_preserves_existing_output(self):
        os.environ['PREVIOUS_UISPSW'] = ''
        self.output.write_bytes(b'existing database')
        with self.assertRaisesRegex(ValueError, 'PREVIOUS_UISPSW'):
            self.recover()
        self.assertEqual(self.output.read_bytes(), b'existing database')

    def test_wrong_previous_key_creates_no_output(self):
        os.environ['PREVIOUS_UISPSW'] = 'wrong-password'
        with self.assertRaisesRegex(ValueError, 'Cannot decrypt'):
            self.recover()
        self.assertFalse(self.output.exists())
        self.assertFalse((self.root / 'step-output').exists())

    def test_missing_later_shard_does_not_publish_partial_database(self):
        (self.shards / 'shards' / self.index['shards'][-1]['name']).unlink()
        with self.assertRaises(FileNotFoundError):
            self.recover()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob('.reassemble-*')), [])

    def test_corrupt_shard_preserves_existing_output(self):
        (self.shards / 'shards' / self.index['shards'][-1]['name']).write_bytes(b'corrupted')
        self.output.write_bytes(b'existing database')
        with self.assertRaises(ValueError):
            self.recover()
        self.assertEqual(self.output.read_bytes(), b'existing database')
        self.assertEqual(list(self.root.glob('.reassemble-*')), [])


if __name__ == '__main__':
    unittest.main()
