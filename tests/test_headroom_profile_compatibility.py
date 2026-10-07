from dataclasses import dataclass
import unittest

from proxy_runtime import _protected_coding_profile


class ProtectedCodingProfileTests(unittest.TestCase):
    def test_current_profile_without_effort_router_preserves_input(self):
        @dataclass(frozen=True)
        class Profile:
            compress_user_messages: bool = True
            compress_system_messages: bool = True
            protect_reads: bool = True

        original = Profile()
        protected = _protected_coding_profile(original)
        self.assertFalse(protected.compress_user_messages)
        self.assertFalse(protected.compress_system_messages)
        self.assertTrue(protected.protect_reads)
        self.assertTrue(original.compress_user_messages)

    def test_legacy_profile_also_disables_effort_routing(self):
        @dataclass(frozen=True)
        class Profile:
            compress_user_messages: bool = True
            compress_system_messages: bool = True
            effort_router: bool = True

        protected = _protected_coding_profile(Profile())
        self.assertFalse(protected.effort_router)
        self.assertFalse(protected.compress_user_messages)
        self.assertFalse(protected.compress_system_messages)

    def test_missing_input_protection_capability_fails_closed(self):
        @dataclass(frozen=True)
        class Profile:
            effort_router: bool = True

        with self.assertRaises(TypeError):
            _protected_coding_profile(Profile())


if __name__ == '__main__':
    unittest.main()
