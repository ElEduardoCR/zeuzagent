import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QCloseEvent
from zeuzedit_desktop.ui import Window, Settings, FindDialog
from zeuzedit_desktop import core


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.window = Window(Settings(Path(self.temporary.name) / "settings.json"), restore=False)

    def tearDown(self):
        for index in range(self.window.tabs.count()):
            self.window.tabs.widget(index).document().setModified(False)
        self.window.close()
        self.app.processEvents()
        self.temporary.cleanup()

    def test_edit_transform_and_undo_are_one_operation(self):
        editor = self.window.editor()
        editor.setPlainText("G1X1\nG1X2\n")
        editor.document().setModified(False)
        self.window.apply(core.renumber)
        self.assertEqual(editor.toPlainText(), "N10 G1X1\nN20 G1X2\n")
        self.assertTrue(editor.document().isModified())
        editor.undo()
        self.assertEqual(editor.toPlainText(), "G1X1\nG1X2\n")

    def test_find_replace_and_unicode_tool_selection(self):
        editor = self.window.editor()
        editor.setPlainText("(工具🙂 T99)\nT0808\nG1X1\n")
        self.window.next_tool()
        self.assertEqual(editor.textCursor().selectedText(), "T0808")
        find = FindDialog(self.window)
        find.find.setText("G1")
        find.replace.setText("G0")
        find.next()
        self.assertEqual(editor.textCursor().selectedText(), "G1")
        find.one()
        self.assertIn("G0X1", editor.toPlainText())
        find.close()

    def test_cancel_close_preserves_dirty_tab(self):
        editor = self.window.editor()
        editor.insertPlainText("G1X1\n")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Cancel):
            self.assertFalse(self.window.close_tab(0))
        self.assertEqual(self.window.tabs.count(), 1)
        self.assertEqual(editor.toPlainText(), "G1X1\n")

    def test_cancel_quit_preserves_all_tabs(self):
        self.window.editor().insertPlainText("G1X1\n")
        self.window.new_document()
        self.window.editor().insertPlainText("G2X2\n")
        event = QCloseEvent()
        with patch.object(QMessageBox, "question", side_effect=[QMessageBox.Discard, QMessageBox.Cancel]):
            self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertEqual(self.window.tabs.count(), 2)

    def test_tab_identity_and_atomic_save_with_crlf(self):
        path = Path(self.temporary.name) / "sample.nc"
        path.write_bytes(b"G1X1\r\nM30\r\n")
        self.window.open_file(path)
        self.window.open_file(path)
        self.assertEqual(self.window.tabs.count(), 2)
        self.window.apply(lambda text: text.replace("X1", "X2"))
        self.assertTrue(self.window.save_document())
        self.assertEqual(path.read_bytes(), b"G1X2\r\nM30\r\n")


if __name__ == "__main__":
    unittest.main()
