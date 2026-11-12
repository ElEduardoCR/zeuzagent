import tempfile
import os
import unittest
from pathlib import Path
from zeuzedit_desktop.document_io import Document


class DocumentTests(unittest.TestCase):
    def test_unchanged_byte_preservation(self):
        for source in [b"\xef\xbb\xbf(Unicode \xc3\xa9)\r\nG1X1\r\n", b"(Latin-1 \xe9)\rG1X1", b"G1X1\r\nG2X2\nM30\r"]:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "sample.nc"
                path.write_bytes(source)
                document = Document.read(path)
                document.save(document.text)
                self.assertEqual(path.read_bytes(), source)

    def test_edit_preserves_encoding_endings_and_no_final_newline(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.nc"
            path.write_bytes(b"(pi\xf1on)\r\nG1X1\r\nM30")
            document = Document.read(path)
            document.save(document.text.replace("X1", "X2"))
            self.assertEqual(path.read_bytes(), b"(pi\xf1on)\r\nG1X2\r\nM30")

    def test_external_change_cannot_be_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.nc"
            path.write_bytes(b"G1X1\n")
            document = Document.read(path)
            path.write_bytes(b"G1X999\n")
            with self.assertRaisesRegex(ValueError, "cambió"):
                document.save("G1X2\n")
            self.assertEqual(path.read_bytes(), b"G1X999\n")

    def test_latin1_refuses_lossy_save_and_binary_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.nc"
            path.write_bytes(b"(\xe9)\nG1X1\n")
            document = Document.read(path)
            with self.assertRaises(UnicodeEncodeError):
                document.save(document.text + "(工具)\n")
            self.assertEqual(path.read_bytes(), b"(\xe9)\nG1X1\n")
            path.write_bytes(b"\0\0binary")
            with self.assertRaises(ValueError):
                Document.read(path)

    def test_external_same_size_change_with_preserved_timestamp_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.nc"
            path.write_bytes(b"G1X1\n")
            original_stat = path.stat()
            document = Document.read(path)
            path.write_bytes(b"G1X9\n")
            os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            with self.assertRaisesRegex(ValueError, "cambió"):
                document.save("G1X2\n")
            self.assertEqual(path.read_bytes(), b"G1X9\n")


if __name__ == "__main__":
    unittest.main()
