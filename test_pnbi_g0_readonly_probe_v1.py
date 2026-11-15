#!/usr/bin/env python3
"""Offline synthetic link-safety tests; never contacts Buildings Department."""
import importlib.util
import unittest
from pathlib import Path

PROBE = Path(__file__).parent / "scripts" / "pnbi_g0_readonly_probe_v1.py"
spec = importlib.util.spec_from_file_location("pnbi_g0_readonly_probe_v1", PROBE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def official_row(index, *, href=None, label="Signed Copy"):
    if href is None:
        href = module.SIGNED_PREFIX + f"PNBI{index:03}se.pdf"
    return (f'<tr><td>PNBI-{index}</td>'
            f'<td><a href="{href}">{label}</a></td></tr>')


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.index = "<html><table>" + "".join(
            official_row(i) for i in range(1, 11)
        ) + "</table></html>"

    def test_valid_ten(self):
        actual = module.extract(self.index)
        self.assertEqual(sorted(actual), list(range(1, 11)))
        self.assertTrue(actual[2].endswith("PNBI002se.pdf"))

    def test_missing_link_holds(self):
        with self.assertRaisesRegex(ValueError, "INCOMPLETE"):
            module.extract(self.index.replace(official_row(5), ""))

    def test_duplicate_signed_link_holds(self):
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            module.extract(self.index + official_row(2))

    def test_off_domain_holds(self):
        hostile = self.index.replace(
            module.SIGNED_PREFIX + "PNBI003se.pdf", "https://evil.example/PNBI003se.pdf"
        )
        with self.assertRaisesRegex(ValueError, "UNSAFE"):
            module.extract(hostile)

    def test_wrong_language_holds(self):
        wrong = self.index.replace("/doc/en/", "/doc/tc/")
        with self.assertRaisesRegex(ValueError, "NON_ENGLISH"):
            module.extract(wrong)

    def test_obsolete_link_is_not_selected(self):
        older = ("<a href='" + module.PREFIX
                 + "obsolete/PNBI006_2013.pdf'>Obsolete Versions</a>")
        self.assertEqual(module.extract(self.index + older), module.extract(self.index))

    def test_out_of_scope_signed_link_holds(self):
        with self.assertRaisesRegex(ValueError, "OUT_OF_SCOPE"):
            module.extract(self.index + official_row(11))

    def test_filename_identity_mismatch_holds(self):
        wrong = self.index.replace("PNBI003se.pdf", "another.pdf")
        with self.assertRaisesRegex(ValueError, "UNRECOGNIZED"):
            module.extract(wrong)

    def test_unsigned_detail_pdf_is_not_signed_copy(self):
        unsafe = self.index.replace(
            module.SIGNED_PREFIX + "PNBI001se.pdf",
            module.PREFIX + "PNBI001.pdf",
        )
        with self.assertRaisesRegex(ValueError, "WRONG_SIGNED_PATH"):
            module.extract(unsafe)

    def test_legacy_obsolete_pdf_must_not_be_signed_candidate(self):
        unsafe = self.index.replace(
            module.SIGNED_PREFIX + "PNBI006se.pdf",
            module.PREFIX + "obsolete/PNBI006_2013.pdf",
        )
        with self.assertRaisesRegex(ValueError, "WRONG_SIGNED_PATH"):
            module.extract(unsafe)

    def test_signed_copy_wrong_suffix_holds(self):
        unsafe = self.index.replace("PNBI007se.pdf", "PNBI007old.pdf")
        with self.assertRaisesRegex(ValueError, "UNRECOGNIZED"):
            module.extract(unsafe)

    def test_signed_copy_query_string_holds(self):
        unsafe = self.index.replace("PNBI008se.pdf", "PNBI008se.pdf?ref=ignored")
        with self.assertRaisesRegex(ValueError, "UNSAFE"):
            module.extract(unsafe)

    def test_html_nested_label(self):
        html = self.index.replace(">Signed Copy<", ">Signed <strong>Copy</strong><")
        self.assertEqual(len(module.extract(html)), 10)


if __name__ == "__main__":
    unittest.main()
