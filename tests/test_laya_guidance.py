from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bundle_integrations
from disable_bundle import disable_guidance


def test_router_guidance_enable_disable_preserves_user_bytes():
    original = b'Personal preference\r\n'
    enabled = bundle_integrations.laya_guidance(original, True)
    assert enabled != original
    assert bundle_integrations.laya_guidance(enabled, True) == enabled
    assert bundle_integrations.laya_guidance(enabled, False) == original
    assert disable_guidance(enabled).strip() == original.strip()


def test_broken_router_guidance_is_not_overwritten():
    with pytest.raises(ValueError):
        bundle_integrations.laya_guidance(b'<!-- BEGIN CODEX TOKEN SAVER LAYA -->', True)
