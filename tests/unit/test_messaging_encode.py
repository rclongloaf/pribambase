from __future__ import annotations

import importlib
import importlib.util
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_NAME = "_pribambase_messaging_test"


class MessagingEncodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        package_path = PROJECT_ROOT / "blender" / "messaging"
        spec = importlib.util.spec_from_file_location(
            PACKAGE_NAME,
            package_path / "__init__.py",
            submodule_search_locations=[str(package_path)],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not load the messaging package for testing.")
        package = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE_NAME] = package
        spec.loader.exec_module(package)
        cls.encode = importlib.import_module(f"{PACKAGE_NAME}.encode")

    def test_projection_message_layout(self) -> None:
        message = self.encode.uv_map(
            size=(2, 3),
            sprite="a",
            pixels=b"\x10\x20",
            opacity=127,
            layer="Guide",
        )

        self.assertEqual(
            message,
            b"M\x7f\x02\x00\x03\x00\x05\x00\x00\x00Guide"
            b"\x01\x00\x00\x00a\x02\x00\x00\x00\x10\x20",
        )

    def test_batch_prefixes_each_message_with_its_size(self) -> None:
        message = self.encode.batch([b"A", b"BC"])

        self.assertEqual(message, b"[\x02\x00\x01\x00\x00\x00A\x02\x00\x00\x00BC")

    def test_string_length_uses_encoded_bytes(self) -> None:
        value = "ёж"
        encoded = value.encode("utf-8")

        self.assertEqual(
            self.encode.sprite_open(value),
            b"O" + len(encoded).to_bytes(4, "little") + encoded,
        )

    def test_frame_message_uses_one_based_uint32(self) -> None:
        self.assertEqual(self.encode.frame(12), b"A\x0c\x00\x00\x00")
        self.assertEqual(self.encode.guide_frame(12), b"G\x0c\x00\x00\x00")

    def test_workspace_message_carries_portable_asset_identity(self) -> None:
        self.assertEqual(
            self.encode.workspace("Cube", "C:/art/cube.aseprite"),
            b"W\x04\x00\x00\x00Cube\x14\x00\x00\x00C:/art/cube.aseprite",
        )

    def test_canvas_message_carries_size_and_signed_world_origin(self) -> None:
        self.assertEqual(
            self.encode.canvas((4, 5), (-2, 3), "a"),
            b"V\x04\x00\x05\x00\xfe\xff\xff\xff\x03\x00\x00\x00"
            b"\x01\x00\x00\x00a",
        )
