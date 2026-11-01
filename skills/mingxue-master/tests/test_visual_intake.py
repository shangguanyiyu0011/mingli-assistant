from __future__ import annotations

import base64
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("MINGXUE_TEST_SKILL_ROOT", HERE))
if not (ROOT / "scripts/visual_intake.py").is_file():
    ROOT = HERE / "package/mingxue-master"
SPEC = importlib.util.spec_from_file_location("visual_intake", ROOT / "scripts" / "visual_intake.py")
V = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V)

# An actual blank 8 x 6 JPEG generated for this test fixture.
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCAAGAAgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD8qqKKKAP/2Q=="
)


def chunk(kind, value):
    return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xFFFFFFFF)


def png(width=8, height=6, extra=b""):
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + extra + chunk(b"IDAT", zlib.compress((b"\x00" + bytes(width * 3)) * height)) + chunk(b"IEND", b""))


class VisualIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def image(self, data, name="test.png"):
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_png_structure_and_actual_dimensions(self):
        result = V.intake("palm", self.image(png()))
        self.assertEqual((result["image"]["format"], result["image"]["width"], result["image"]["height"]), ("PNG", 8, 6))
        self.assertEqual(result["image"]["validation"], "container_structure_only")
        self.assertFalse(result["image_content_analysis"])
        self.assertFalse(result["uploaded"])
        self.assertEqual(result["user_reported_observations"]["features"], [])

    def test_png_crc_failure(self):
        value = bytearray(png())
        value[29] ^= 1
        with self.assertRaisesRegex(V.IntakeError, "checksum"):
            V.inspect_image(self.image(value))

    def test_png_truncation(self):
        with self.assertRaises(V.IntakeError):
            V.inspect_image(self.image(png()[:-5]))

    def test_filename_does_not_determine_format(self):
        info, notes = V.inspect_image(self.image(png(), "fake.jpg"))
        self.assertEqual(info["format"], "PNG")
        self.assertTrue(any("extension" in item for item in notes))
        with self.assertRaises(V.IntakeError):
            V.inspect_image(self.image(b"not an image", "fake.png"))

    def test_jpeg_dimensions(self):
        info, _ = V.inspect_image(self.image(JPEG, "test.jpg"))
        self.assertEqual((info["width"], info["height"]), (8, 6))
        self.assertFalse(info["pixel_decode_performed"])

    def test_jpeg_missing_end_marker(self):
        with self.assertRaises(V.IntakeError):
            V.inspect_image(self.image(JPEG[:-2], "test.jpg"))

    def test_exif_rotation_does_not_expose_other_metadata(self):
        tiff = (b"II" + struct.pack("<HIH", 42, 8, 2)
                + struct.pack("<HHI", 0x0112, 3, 1) + struct.pack("<H", 6) + b"\x00\x00"
                + struct.pack("<HHII", 0x8825, 4, 1, 38) + bytes(4)
                + b"private-device-and-location")
        exif = b"Exif\x00\x00" + tiff
        value = JPEG[:2] + b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif + JPEG[2:]
        info, _ = V.inspect_image(self.image(value, "rotated.jpg"))
        self.assertEqual((info["orientation"], info["display_width"], info["display_height"]), (6, 6, 8))
        serialized = json.dumps(info)
        self.assertNotIn("private-device", serialized)
        self.assertNotIn("gps", serialized.lower())

    def test_png_text_values_not_returned(self):
        info, _ = V.inspect_image(self.image(png(extra=chunk(b"tEXt", b"Author\x00private-person"))))
        self.assertTrue(info["text_metadata_present"])
        self.assertNotIn("private-person", json.dumps(info))

    def test_no_image_is_not_observed(self):
        result = V.intake("palm", observations={"hand": "left", "features": [{"region": "thumb_arc", "shape": "curved", "visibility": "clear"}]})
        self.assertEqual(result["observation_status"], "not_observed")
        self.assertEqual(result["user_reported_observations"]["hand"], "left")

    def test_quality_is_unknown_unless_reported(self):
        result = V.intake("face", self.image(png()))
        self.assertTrue(all(value == "unknown" for value in result["user_reported_observations"]["quality"].values()))

    def test_explicit_quality_and_side(self):
        result = V.intake('palm', observations={'hand': 'left', 'quality': {'clarity': 'blurry', 'cropping': 'partial', 'occlusion': 'present', 'mirrored': 'unknown', 'shadow': 'present', 'perspective': 'angled'}})
        report = result['user_reported_observations']
        self.assertEqual(report['hand'], 'left')
        self.assertEqual(report['quality']['cropping'], 'partial')
        self.assertEqual(report['quality']['mirrored'], 'unknown')
        self.assertEqual(report['quality']['shadow'], 'present')
        self.assertFalse(result['image_content_analysis'])
    def test_reject_inference_and_extra_fields(self):
        for raw in ({"personality": "honest"}, {"health": "healthy"}, {"quality": {"intelligence": "high"}},
                    {"features": [{"region": "thumb_arc", "shape": "honest", "visibility": "clear"}]}, []):
            with self.subTest(raw=raw), self.assertRaises(V.IntakeError):
                V.intake("palm", observations=raw)

    def test_face_rejects_hand_metadata(self):
        with self.assertRaises(V.IntakeError):
            V.intake("face", observations={"hand": "left"})

    def test_missing_file(self):
        with self.assertRaises(V.IntakeError):
            V.inspect_image(self.root / "missing.png")

    def test_file_size_limit(self):
        path = self.root / "large.png"
        with path.open("wb") as handle:
            handle.truncate(V.MAX_BYTES + 1)
        with self.assertRaisesRegex(V.IntakeError, "30 MiB"):
            V.inspect_image(path)

    def test_cli_returns_json_error(self):
        process = subprocess.run([sys.executable, "-X", "utf8", "-B", str(ROOT / "scripts" / "visual_intake.py"), "--system", "palm", "--image", str(self.root / "missing.png")], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 2)
        self.assertFalse(json.loads(process.stdout)["ok"])
        self.assertEqual(process.stderr, "")


if __name__ == "__main__":
    unittest.main()


