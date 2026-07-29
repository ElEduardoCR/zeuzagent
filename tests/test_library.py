import tempfile
import unittest
from pathlib import Path

from zeuzagent.library import Conflict, InvalidPath, ProgramLibrary


class ProgramLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.library = ProgramLibrary(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_complete_program_lifecycle(self) -> None:
        created = self.library.create("", "O1000.nc")
        self.assertEqual(created["path"], "O1000.nc")

        saved = self.library.write("O1000.nc", "O1000\r\nM30\r\n")
        loaded = self.library.read("O1000.nc")
        self.assertEqual(loaded["content"], "O1000\r\nM30\r\n")
        self.assertEqual(saved["size"], len(loaded["content"]))

        listing = self.library.list("")
        self.assertEqual([entry["name"] for entry in listing["entries"]], ["O1000.nc"])
        self.assertEqual(self.library.search("1000")[0]["path"], "O1000.nc")

        self.library.delete("O1000.nc")
        self.assertEqual(self.library.list("")["entries"], [])

    def test_path_traversal_is_rejected(self) -> None:
        with self.assertRaises(InvalidPath):
            self.library.read("../secreto.txt")
        with self.assertRaises(InvalidPath):
            self.library.write("sub/../../secreto.txt", "x")

    def test_optimistic_concurrency_prevents_overwrite(self) -> None:
        self.library.write("O2000.nc", "primera")
        loaded = self.library.read("O2000.nc")
        self.library.write("O2000.nc", "externa")
        with self.assertRaises(Conflict):
            self.library.write(
                "O2000.nc",
                "copia vieja",
                expected_modified=loaded["modified"],
            )

    def test_external_change_wait_can_be_released(self) -> None:
        version = self.library.tracker.version
        self.library.write("O3000.nc", "M30")
        self.assertGreater(self.library.tracker.wait_for_change(version, 0), version)


if __name__ == "__main__":
    unittest.main()

