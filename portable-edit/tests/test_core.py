import unittest
from zeuzedit_desktop import core


class CoreTests(unittest.TestCase):
    def test_renumber_preserves_headers_comments_and_endings(self):
        text = "%\r\nO123\r\n(comment\r\ncontinued T88)\r\nN2G1X1\r\n; keep\r\n\r\nM30\r\n%"
        result = core.renumber(text)
        self.assertEqual(result, "%\r\nO123\r\n(comment\r\ncontinued T88)\r\nN10 G1X1\r\n; keep\r\n\r\nN20 M30\r\n%")

    def test_missing_only_and_remove(self):
        self.assertEqual(core.renumber("N5 G0X0\rG1X2\r", missing_only=True), "N5 G0X0\rN10 G1X2\r")
        self.assertEqual(core.remove_numbers("N5 G0\r\nN15M30"), "G0\r\nM30")
        self.assertEqual(core.remove_numbers("(comment\nN8 keep\n)\nN10G1\n"), "(comment\nN8 keep\n)\nG1\n")

    def test_scaling_respects_comments_compact_words_and_decimal_format(self):
        source = "G1F100 (F900) ; F800\r\nF.4\r\nS1000\r\n(OPEN\r\nF300)\r\n"
        self.assertEqual(core.scale_words(source, "F", .5), "G1F50 (F900) ; F800\r\nF0.2\r\nS1000\r\n(OPEN\r\nF300)\r\n")
        with self.assertRaises(ValueError):
            core.scale_words("F100", "F", float("inf"))
        self.assertEqual(core.scale_words("F101 F-101", "F", .5), "F51 F-51")

    def test_remove_mcodes_exact_only(self):
        self.assertEqual(core.remove_mcodes("N1M08\r\n\r\nN2G1X1M8 (M8)\r\nM80 M8.1\r\nM9\r\n", {8}), "\r\nN2G1X1 (M8)\r\nM80 M8.1\r\nM9\r\n")

    def test_comment_spacing_and_case_survive(self):
        self.assertEqual(core.format_spacing("g1   x2 (keep   spacing) ; comment   spacing\r\n"), "g1 x2 (keep   spacing) ; comment   spacing\r\n")
        self.assertEqual(core.uppercase_code("g1 x2 (small text) ; other\n"), "G1 X2 (small text) ; other\n")

    def test_analysis_ignores_commented_tools_and_warns_incremental(self):
        result = core.analyze("(T99 X100)\nG21\nG91\nT2M6\nG1X-2.5Y4\nX3\nM30\n")
        self.assertEqual(result.tools, ("2",))
        self.assertEqual(result.axes["X"], (-2.5, 3))
        self.assertEqual(result.units, "Milímetros (G21)")
        self.assertTrue(any("G91" in value for value in result.warnings))


if __name__ == "__main__":
    unittest.main()
