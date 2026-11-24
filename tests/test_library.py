import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from zeuzagent.library import Conflict, InvalidPath, LibraryError, ProgramLibrary


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

    @contextmanager
    def coarse_replacements(self, target, *, writable_clock=True):
        """Model writes within one tick and a disk rounding utime to two seconds."""
        tick = target.stat().st_mtime_ns
        temporary_files = {}
        real_mkstemp, real_fdopen, real_utime = tempfile.mkstemp, os.fdopen, os.utime

        def make_temporary(*args, **kwargs):
            descriptor, name = real_mkstemp(*args, **kwargs)
            temporary_files[descriptor] = name
            return descriptor, name

        @contextmanager
        def close_with_same_tick(descriptor, *args, **kwargs):
            with real_fdopen(descriptor, *args, **kwargs) as handle:
                yield handle
            real_utime(temporary_files[descriptor], ns=(tick, tick))

        def coarse_utime(path, *, ns):
            rounded = tick + ((ns[1] - tick) // 2_000_000_000) * 2_000_000_000 if writable_clock else tick
            real_utime(path, ns=(ns[0], rounded))

        with patch("zeuzagent.library.tempfile.mkstemp", side_effect=make_temporary), \
             patch("zeuzagent.library.os.fdopen", side_effect=close_with_same_tick), \
             patch("zeuzagent.library.os.utime", side_effect=coarse_utime):
            yield

    def test_same_tick_replacement_invalidates_old_revision_on_coarse_disk(self):
        self.library.write("O4000.nc", "primera")
        old = self.library.read("O4000.nc")
        target = self.library.root / "O4000.nc"
        with self.coarse_replacements(target):
            updated = self.library.write("O4000.nc", "externa", expected_modified=old["modified"])
            self.assertGreater(updated["modified"] - old["modified"], 0.000001)
            with self.assertRaises(Conflict):
                self.library.write("O4000.nc", "copia vieja", expected_modified=old["modified"])
        self.assertEqual(target.read_bytes(), b"externa")

    def test_indistinguishable_revision_preserves_previous_file(self):
        self.library.write("O5000.nc", "original")
        target = self.library.root / "O5000.nc"
        with self.coarse_replacements(target, writable_clock=False):
            with self.assertRaisesRegex(LibraryError, "conservó"):
                self.library.write("O5000.nc", "replacement")
        self.assertEqual(target.read_bytes(), b"original")
        self.assertEqual(list(self.library.root.glob(".zeuz-*")), [])

    def test_concurrent_library_instances_allow_only_one_edit_of_same_revision(self):
        self.library.write("O6000.nc", "original")
        modified = self.library.read("O6000.nc")["modified"]
        barrier = threading.Barrier(8)
        def save(index):
            library = ProgramLibrary(self.library.root)
            barrier.wait(timeout=5)
            try:
                library.write("O6000.nc", str(index), expected_modified=modified)
                return index
            except Conflict:
                return None
        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(save, range(8)))
        accepted = [index for index in results if index is not None]
        self.assertEqual(len(accepted), 1)
        self.assertEqual((self.library.root / "O6000.nc").read_text(), str(accepted[0]))

    def test_preview_revision_stays_with_opened_contents_during_replacement(self):
        self.library.write("O7000.nc", "original")
        target = self.library.root / "O7000.nc"
        original = self.library.read("O7000.nc")
        real_open = Path.open
        @contextmanager
        def replace_after_close(path, *args, **kwargs):
            with real_open(path, *args, **kwargs) as handle:
                yield handle
            if path == target and args == ("rb",):
                self.library.write("O7000.nc", "external replacement")
        with patch.object(Path, "open", replace_after_close):
            preview = self.library.read("O7000.nc")
        self.assertEqual(preview["content"], "original")
        self.assertEqual(preview["modified"], original["modified"])
        with self.assertRaises(Conflict):
            self.library.write("O7000.nc", "stale preview", expected_modified=preview["modified"])
        self.assertEqual(target.read_bytes(), b"external replacement")


if __name__ == "__main__":
    unittest.main()

