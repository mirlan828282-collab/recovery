# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import ntfs_recovery


class NtfsParserTests(unittest.TestCase):
    def test_valid_boot_sector(self):
        boot = bytearray(512)
        boot[3:11] = b"NTFS    "
        boot[11:13] = (512).to_bytes(2, "little")
        boot[13] = 8
        boot[40:48] = (100000).to_bytes(8, "little")
        boot[48:56] = (4).to_bytes(8, "little")
        boot[64] = (-10) & 0xff
        info = ntfs_recovery._valid_boot(bytes(boot))
        self.assertIsNotNone(info)
        self.assertEqual(info["record_size"], 1024)
        self.assertEqual(info["cluster"], 4096)

    def test_reject_non_ntfs_boot_sector(self):
        self.assertIsNone(ntfs_recovery._valid_boot(bytes(512)))

    def test_decode_simple_data_run(self):
        # One run: 3 clusters starting at LCN 5, then terminator.
        runs = ntfs_recovery._parse_runs(bytes([0x11, 3, 5, 0]), 4096)
        self.assertEqual(runs, [(5 * 4096, 3 * 4096)])

    def test_decode_sparse_data_run(self):
        runs = ntfs_recovery._parse_runs(bytes([0x01, 2, 0]), 4096)
        self.assertEqual(runs, [(None, 2 * 4096)])


if __name__ == "__main__":
    unittest.main()
