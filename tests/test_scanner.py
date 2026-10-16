import os
import shutil
import tempfile
import unittest

from core.database import get_database_connection, get_db_path, initialize_database
from core.media_ops import create_album, list_albums, rename_album
from core.scanner import ScanState, is_ignored, walk_directory


class TestScannerAlbumRouting(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="scanner_unittest_")
        os.makedirs(os.path.join(self.temp_dir, "albums"), exist_ok=True)
        self.db_path = get_db_path(self.temp_dir)
        conn = get_database_connection(self.db_path)
        initialize_database(conn)
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_is_ignored_segments(self):
        # Single name segment matching
        self.assertTrue(is_ignored("photos/raw/image.jpg", ["raw"]))
        # Partial substring in a name should NOT match
        self.assertFalse(is_ignored("photos/strawberry.jpg", ["raw"]))
        self.assertFalse(is_ignored("contemporary/image.jpg", ["temp"]))
        # Multi-segment pattern matching
        self.assertTrue(is_ignored("backup/photos/raw/pic.png", ["photos/raw"]))
        self.assertFalse(is_ignored("backup/photos/edited/pic.png", ["photos/raw"]))

    def test_scanner_subfolder_album_creation(self):
        # 1. Create a root-level file
        with open(os.path.join(self.temp_dir, "loose_pic.jpg"), "wb") as f:
            f.write(b"loose file bytes")

        # 2. Create a subfolder with media
        vacation_dir = os.path.join(self.temp_dir, "Vacation")
        os.makedirs(vacation_dir, exist_ok=True)
        with open(os.path.join(vacation_dir, "beach.jpg"), "wb") as f:
            f.write(b"beach bytes")
        with open(os.path.join(vacation_dir, "sunset.png"), "wb") as f:
            f.write(b"sunset bytes")

        # 3. Create a nested subfolder with media
        nested_dir = os.path.join(self.temp_dir, "2024", "Events")
        os.makedirs(nested_dir, exist_ok=True)
        with open(os.path.join(nested_dir, "party.mp4"), "wb") as f:
            f.write(b"party video bytes")

        scan_state = ScanState(self.temp_dir)
        walk_directory(
            drive_path=self.temp_dir,
            start_dir=self.temp_dir,
            db_path=self.db_path,
            scan_state=scan_state,
            ignore_list=["albums"],
        )

        self.assertEqual(scan_state.media_found, 4)

        # Verify database albums
        conn = get_database_connection(self.db_path)
        albums = conn.execute(
            "SELECT id, name, relative_path, media_count FROM albums"
        ).fetchall()
        album_map = {a["name"]: a for a in albums}

        self.assertIn("unknown", album_map)
        self.assertIn("Vacation", album_map)
        self.assertIn("2024/Events", album_map)

        self.assertEqual(album_map["unknown"]["media_count"], 1)
        self.assertEqual(album_map["Vacation"]["media_count"], 2)
        self.assertEqual(album_map["2024/Events"]["media_count"], 1)

        # Verify files on disk inside albums
        self.assertTrue(
            os.path.exists(
                os.path.join(self.temp_dir, "albums", "unknown", "loose_pic.jpg")
            )
        )
        self.assertTrue(
            os.path.exists(
                os.path.join(self.temp_dir, "albums", "Vacation", "beach.jpg")
            )
        )
        self.assertTrue(
            os.path.exists(
                os.path.join(self.temp_dir, "albums", "Vacation", "sunset.png")
            )
        )
        self.assertTrue(
            os.path.exists(
                os.path.join(self.temp_dir, "albums", "2024", "Events", "party.mp4")
            )
        )

        # Verify empty source directories pruned
        self.assertFalse(os.path.exists(vacation_dir))
        self.assertFalse(os.path.exists(nested_dir))
        self.assertFalse(os.path.exists(os.path.join(self.temp_dir, "2024")))

        conn.close()


if __name__ == "__main__":
    unittest.main()
