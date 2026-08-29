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
        package_path = PROJECT_ROOT / "messaging"
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

    def test_image_message_layout(self) -> None:
        message = self.encode.image("a", (2, 3), b"\x10\x20")

        self.assertEqual(
            message,
            b"I\x02\x00\x03\x00\x01\x00\x00\x00a\x02\x00\x00\x00\x10\x20",
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
