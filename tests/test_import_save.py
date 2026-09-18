import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.encrypt import encrypt_es3
from lib.import_save import SAVE_PASSWORD, import_es3


class ImportSaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backups = self.root / 'backups'
        self.backups.mkdir()
        self.source = self.root / 'my save.ES3'
        self.data = encrypt_es3(json.dumps({
            'dictionaryOfDictionaries': {'value': {'runStats': {'level': 7}}}
        }).encode(), SAVE_PASSWORD)
        self.source.write_bytes(self.data)

    def test_import_preserves_original_and_uses_matching_names(self):
        target = import_es3(self.source, self.backups)
        self.assertTrue(target.name.startswith('REPO_SAVE_'))
        self.assertEqual((target / (target.name + '.es3')).read_bytes(), self.data)
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_repeated_import_never_overwrites(self):
        first = import_es3(self.source, self.backups)
        second = import_es3(self.source, self.backups)
        self.assertNotEqual(first, second)
        self.assertEqual((first / (first.name + '.es3')).read_bytes(), self.data)

    def test_invalid_save_creates_no_backup(self):
        for data in (b'broken', encrypt_es3(b'{"unrelated": true}', SAVE_PASSWORD)):
            self.source.write_bytes(data)
            with self.assertRaises(ValueError):
                import_es3(self.source, self.backups)
            self.assertEqual(list(self.backups.iterdir()), [])

    def test_failed_write_removes_partial_backup(self):
        with patch.object(Path, 'write_bytes', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                import_es3(self.source, self.backups)
        self.assertEqual(list(self.backups.iterdir()), [])
        self.assertEqual(self.source.read_bytes(), self.data)


class DropIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, {
            'QT_QPA_PLATFORM': 'offscreen',
            'XDG_DATA_HOME': cls.temp.name + '/data',
            'XDG_CACHE_HOME': cls.temp.name + '/cache',
        })
        cls.env.start()
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        cls.game_patch = patch("repo_save_manager.find_linux_saves", return_value=Path(cls.temp.name) / "game")
        cls.game_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.game_patch.stop()
        cls.env.stop()
        cls.temp.cleanup()

    def test_viewport_drop_imports_and_displays_backup(self):
        from PyQt6.QtCore import QMimeData, QPoint, QPointF, QUrl, Qt
        from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
        from repo_save_manager import RepoSaveManager
        source = Path(self.temp.name) / 'Dropped save.es3'
        data = encrypt_es3(json.dumps({
            'dictionaryOfDictionaries': {'value': {'runStats': {'level': 7}}}
        }).encode(), SAVE_PASSWORD)
        source.write_bytes(data)
        broken = Path(self.temp.name) / 'broken.es3'
        broken.write_bytes(b'invalid save')
        window = RepoSaveManager()
        self.addCleanup(window.close)
        window.settings['show_backup_saves'] = False
        window.show()
        self.app.processEvents()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(source)), QUrl.fromLocalFile(str(broken))])
        actions = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
        enter = QDragEnterEvent(QPoint(10, 10), actions, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        move = QDragMoveEvent(QPoint(10, 10), actions, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        drop = QDropEvent(QPointF(10, 10), actions, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        with patch('repo_save_manager.QMessageBox.warning') as warning:
            for event in (enter, move, drop):
                self.app.sendEvent(window.save_table.viewport(), event)
                self.assertTrue(event.isAccepted())
                self.assertEqual(event.dropAction(), Qt.DropAction.CopyAction)
            warning.assert_called_once()
        self.assertEqual(source.read_bytes(), data)
        self.assertEqual(window.save_table.rowCount(), 1)
        self.assertEqual(window.save_table.item(0, 4).text(), '8')
        self.assertTrue(window.get_selected_save_info()['is_backup'])
        self.assertTrue(window.restore_btn.isEnabled())
        self.assertTrue(window.settings['show_backup_saves'])
        self.assertIn('Dropped save.es3', window.save_table.item(0, 3).text())

    def test_backup_button_and_live_editor_support_standalone_save(self):
        from PyQt6.QtWidgets import QDialog, QMessageBox
        from repo_save_manager import RepoSaveManager
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            'XDG_DATA_HOME': temporary + '/data',
        }):
            game = Path(temporary) / 'game'
            game.mkdir()
            name = 'REPO_SAVE_2026_03_27_14_05_47'
            source = game / (name + '.es3')
            data = encrypt_es3(json.dumps({
                'dictionaryOfDictionaries': {'value': {'runStats': {'level': 7}}}
            }).encode(), SAVE_PASSWORD)
            source.write_bytes(data)
            window = RepoSaveManager()
            self.addCleanup(window.close)
            window.settings['game_saves_path'] = str(game)
            window.apply_save_path()
            with patch('repo_save_manager.QDialog.exec', return_value=QDialog.DialogCode.Accepted), \
                 patch('repo_save_manager.QMessageBox.information'), \
                 patch('repo_save_manager.QMessageBox.critical') as error:
                window.create_backup()
                error.assert_not_called()
            backup_file = window.backup_path / name / source.name
            self.assertEqual(backup_file.read_bytes(), data)
            self.assertEqual(source.read_bytes(), data)
            window.save_table.selectRow(0)
            with patch('repo_save_manager.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
                 patch('repo_save_manager.QMessageBox.information'), \
                 patch('repo_save_manager.QMessageBox.critical') as error:
                window.insert_into_repo()
                error.assert_not_called()
            self.assertEqual(source.read_bytes(), data)
            self.assertFalse((game / name).exists())
            window.settings['live_edits_enabled'] = True
            window.refresh_save_list()
            self.assertEqual(window.save_table.rowCount(), 2)
            for row in range(2):
                window.save_table.selectRow(row)
                with patch('repo_save_manager.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
                     patch('repo_save_manager.QMessageBox.critical') as error, \
                     patch('repo_save_manager.SaveEditor') as editor:
                    editor.return_value.exec.return_value = QDialog.DialogCode.Rejected
                    window.open_in_editor()
                    editor.assert_called_once()
                    self.assertEqual(Path(editor.call_args.args[3]), source)
                    error.assert_not_called()
            self.assertEqual(source.read_bytes(), data)

    def test_primary_save_refresh_and_editor_ignore_recovery_files(self):
        from repo_save_manager import RepoSaveManager, SaveEditor
        from PyQt6.QtCore import Qt
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'XDG_DATA_HOME': temporary + '/data'}):
            folder = Path(temporary) / 'game' / 'REPO_SAVE_test'
            folder.mkdir(parents=True)
            def payload(level, charge):
                return encrypt_es3(json.dumps({'dictionaryOfDictionaries': {'value': {
                    'runStats': {'level': level, 'chargingStationCharge': charge}
                }}}).encode(), SAVE_PASSWORD)
            (folder / 'REPO_SAVE_test_BACKUP14.es3').write_bytes(payload(2, 5))
            primary = folder / 'REPO_SAVE_test.es3'
            primary.write_bytes(payload(5, 7))
            window = RepoSaveManager()
            self.addCleanup(window.close)
            window.settings['game_saves_path'] = str(folder.parent)
            window.apply_save_path()
            window.refresh_save_list()
            self.assertEqual(window.save_table.rowCount(), 1)
            self.assertEqual(window.save_table.item(0, 4).text(), '6')
            window.save_table.selectRow(0)
            self.assertFalse(window.edit_button.isEnabled())
            primary.write_bytes(payload(6, 9))
            window.refresh_if_changed()
            self.assertEqual(window.save_table.item(0, 4).text(), '7')
            self.assertEqual(window.get_selected_save_info()['path'], str(folder))
            from lib.save_paths import save_files
            editor = SaveEditor(str(save_files(folder)[0]), window)
            self.addCleanup(editor.close)
            self.assertEqual(editor.level_entry.text(), '7')
            self.assertEqual(editor.charging_entry.text(), '9')
            from lib.decrypt import decrypt_es3
            with patch('repo_save_manager.QMessageBox.information'):
                editor.save_changes()
            saved = json.loads(decrypt_es3(primary.read_bytes(), SAVE_PASSWORD))
            self.assertEqual(saved['dictionaryOfDictionaries']['value']['runStats']['level'], 6)
            editor.level_entry.setText('8')
            with patch('repo_save_manager.QMessageBox.information'):
                editor.save_changes()
            saved = json.loads(decrypt_es3(primary.read_bytes(), SAVE_PASSWORD))
            self.assertEqual(saved['dictionaryOfDictionaries']['value']['runStats']['level'], 7)
            before = primary.read_bytes()
            editor.level_entry.setText('0')
            with patch('repo_save_manager.QMessageBox.warning') as warning:
                editor.save_changes()
                warning.assert_called_once()
            self.assertEqual(primary.read_bytes(), before)
            self.assertFalse(window.descriptions_file.exists())

    def test_non_save_and_remote_urls_rejected(self):
        from PyQt6.QtCore import QMimeData, QPoint, QUrl, Qt
        from PyQt6.QtGui import QDragEnterEvent
        from repo_save_manager import BackupTable
        table = BackupTable()
        self.addCleanup(table.close)
        text = Path(self.temp.name) / 'notes.txt'
        text.write_text('notes')
        for url in (QUrl.fromLocalFile(str(text)), QUrl('https://example.com/save.es3'),
                    QUrl.fromLocalFile(self.temp.name)):
            mime = QMimeData()
            mime.setUrls([url])
            event = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, mime,
                                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            self.app.sendEvent(table.viewport(), event)
            self.assertFalse(event.isAccepted())


if __name__ == '__main__':
    unittest.main()
