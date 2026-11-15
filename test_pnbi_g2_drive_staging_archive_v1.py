#!/usr/bin/env python3
"""G2 offline fail-closed contracts; never contacts Drive or BD."""
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
import pnbi_g2_drive_staging_archive_v1 as g2


class ArchiveTests(unittest.TestCase):
    def test_exact_scope_manifest_hash_format(self):
        self.assertEqual(sorted(g2.EXPECTED), list(range(1, 11)))
        for sha, bytes_, pages in g2.EXPECTED.values():
            self.assertRegex(sha, r"^[0-9a-f]{64}$")
            self.assertGreater(bytes_, 0)
            self.assertGreater(pages, 0)

    def test_hash_addressed_filename(self):
        self.assertEqual(
            g2.expected_filename(1),
            "PNBI001_" + g2.EXPECTED[1][0] + ".pdf",
        )

    def test_folder_identity_valid(self):
        def lsjson(path, dirs=False, files=False):
            if path == g2.REMOTE:
                return [{"Name": "_Staging_Incoming", "IsDir": True, "ID": g2.ROOT_ID}]
            if path == g2.ROOT_PATH:
                return [{"Name": "PNBI", "IsDir": True, "ID": g2.PNBI_FOLDER_ID}]
            raise AssertionError("unexpected folder")
        with patch.object(g2, "run", return_value=(g2.REMOTE + "\n").encode()), \
             patch.object(g2, "list_json", side_effect=lsjson):
            g2.check_folder_identity()

    def test_remote_is_not_autoselected(self):
        with patch.object(g2, "run", return_value=b"some-other-remote:\n"):
            with self.assertRaisesRegex(ValueError, "WRITE_REMOTE_NOT_CONFIGURED"):
                g2.check_folder_identity()

    def test_wrong_parent_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "FOLDER_ID_MISMATCH"):
            g2.one_named([{"Name": "_Staging_Incoming", "IsDir": True, "ID": "wrong"}],
                         "_Staging_Incoming", g2.ROOT_ID)

    def test_duplicate_folder_rejected(self):
        folders = [{"Name": "PNBI", "IsDir": True, "ID": g2.PNBI_FOLDER_ID}] * 2
        with self.assertRaisesRegex(ValueError, "FOLDER_MISSING_OR_DUPLICATE"):
            g2.one_named(folders, "PNBI", g2.PNBI_FOLDER_ID)

    def test_existing_variation_rejected(self):
        with self.assertRaisesRegex(ValueError, "EXISTING_SOURCE_VARIANT"):
            g2.check_existing([{"Name": "PNBI001_" + "0" * 64 + ".pdf",
                                "Size": 21971, "ID": "something"}], 1)

    def test_existing_duplicate_rejected(self):
        file = {"Name": g2.expected_filename(1), "Size": 21971, "ID": "a"}
        with self.assertRaisesRegex(ValueError, "EXISTING_SOURCE_VARIANT"):
            g2.check_existing([file, dict(file, ID="b")], 1)

    def test_existing_exact_file_skips_copy(self):
        file = {"Name": g2.expected_filename(1), "Size": 21971, "ID": "drivefile"}
        self.assertTrue(g2.check_existing([file], 1))
        self.assertFalse(g2.check_existing([], 1))

    def test_existing_wrong_size_rejected(self):
        file = {"Name": g2.expected_filename(1), "Size": 2, "ID": "drivefile"}
        with self.assertRaisesRegex(ValueError, "EXISTING_REMOTE_METADATA"):
            g2.check_existing([file], 1)

    def test_list_json_rejects_nondirectory_json(self):
        with patch.object(g2, "run", return_value=b"{}"):
            with self.assertRaisesRegex(ValueError, "NOT_ARRAY"):
                g2.list_json("anything")

    def test_remote_readback_full_sha_pass(self):
        data = b"original source"
        expected = (hashlib.sha256(data).hexdigest(), len(data), 1)
        with patch.dict(g2.EXPECTED, {1: expected}), \
             patch.object(g2, "list_json", return_value=[
                 {"Name": g2.expected_filename(1), "Size": len(data), "ID": "verified123"}
             ]), \
             patch.object(g2, "run", return_value=data):
            self.assertEqual(g2.verify_remote(1), "verified123")

    def test_remote_readback_mismatch_holds(self):
        good = b"original source"
        expected = (hashlib.sha256(good).hexdigest(), len(good), 1)
        with patch.dict(g2.EXPECTED, {1: expected}), \
             patch.object(g2, "list_json", return_value=[
                 {"Name": g2.expected_filename(1), "Size": len(good), "ID": "verified123"}
             ]), \
             patch.object(g2, "run", return_value=b"tampered source"):
            with self.assertRaisesRegex(ValueError, "REMOTE_READBACK_SHA256"):
                g2.verify_remote(1)

    def test_source_identity_and_sha_pass(self):
        data = b"%PDF-1.7\ntrusted candidate\n"
        expected = (hashlib.sha256(data).hexdigest(), len(data), 1)
        with patch.dict(g2.EXPECTED, {1: expected}), \
             patch.object(g2.g1, "fetch_official_index", return_value={
                 1: "https://www.bd.gov.hk/doc/en/resources/codes-and-references/practice-notes-and-circular-letters/pnbi/PNBI001.pdf"
             }), \
             patch.object(g2.g1, "fetch_pdf", return_value=data):
            actual, url = g2.fetch_exact_source(1)
            self.assertEqual(actual, data)
            self.assertTrue(url.endswith("PNBI001.pdf"))

    def test_source_changed_sha_holds(self):
        data = b"%PDF-1.7\nchanged bytes\n"
        with patch.object(g2.g1, "fetch_official_index", return_value={
            1: "https://www.bd.gov.hk/doc/en/resources/codes-and-references/practice-notes-and-circular-letters/pnbi/PNBI001.pdf"
        }), patch.object(g2.g1, "fetch_pdf", return_value=data):
            with self.assertRaisesRegex(ValueError, "SOURCE_BYTES_OR_SHA_CHANGED"):
                g2.fetch_exact_source(1)

    def test_unexpected_source_link_holds(self):
        with patch.object(g2.g1, "fetch_official_index", return_value={
            1: "https://www.bd.gov.hk/doc/en/resources/codes-and-references/practice-notes-and-circular-letters/pnbi/signed/PNBI001se.pdf"
        }):
            with self.assertRaisesRegex(ValueError, "SOURCE_LINK_CHANGED"):
                g2.fetch_exact_source(1)

    def test_archive_new_only_copyto_immutable(self):
        with patch.object(g2, "check_folder_identity"), \
             patch.object(g2, "list_json", return_value=[]), \
             patch.object(g2, "fetch_exact_source", return_value=(b"sample", "officialurl")), \
             patch.object(g2, "run", return_value=b"") as command, \
             patch.object(g2, "verify_remote", return_value="drive-id"):
            result = g2.archive_one(1)
            self.assertEqual(result["outcome"], "NEW_UPLOAD_VERIFIED")
            args = command.call_args.args
            self.assertEqual(args[0:2], ("rclone", "copyto"))
            self.assertIn("--immutable", args)
            self.assertTrue(args[-1].endswith(g2.expected_filename(1)))

    def test_archive_existing_never_reuploads(self):
        existing = [{"Name": g2.expected_filename(1), "Size": 21971, "ID": "same-id"}]
        with patch.object(g2, "check_folder_identity"), \
             patch.object(g2, "list_json", return_value=existing), \
             patch.object(g2, "fetch_exact_source", return_value=(b"sample", "officialurl")), \
             patch.object(g2, "run") as command, \
             patch.object(g2, "verify_remote", return_value="same-id"):
            result = g2.archive_one(1)
            command.assert_not_called()
            self.assertEqual(result["outcome"], "EXISTING_VERIFIED")


if __name__ == "__main__":
    unittest.main()
