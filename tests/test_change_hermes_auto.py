"""change-hermes --auto walks AUTO_ORDER and stops at the first working route."""
import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("ruamel.yaml")
P = Path(__file__).resolve().parents[1] / "bin" / "change-hermes"


def load():
    loader = importlib.machinery.SourceFileLoader("change_hermes", str(P))
    spec = importlib.util.spec_from_loader("change_hermes", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["change_hermes"] = mod
    loader.exec_module(mod)
    return mod


def test_order_routes_exist_in_catalog():
    ch = load()
    for r in ch.AUTO_ORDER:
        assert ch.by_route(r) is not None, r


def test_auto_picks_first_working_and_stops(monkeypatch):
    ch = load()
    tried = []

    def fake(cfg, env, m):
        r = f"{m.provider}:{m.model_id}"
        tried.append(r)
        return (r == ch.AUTO_ORDER[3], "x")

    monkeypatch.setattr(ch, "probe_one", fake)
    o = ch.auto_pick({}, {})
    assert o.route == ch.AUTO_ORDER[3] and o.effort == "medium" and o.ctx == o.model.native_ctx
    assert tried == list(ch.AUTO_ORDER[:4])


def test_auto_none(monkeypatch):
    ch = load()
    monkeypatch.setattr(ch, "probe_one", lambda c, e, m: (False, "no"))
    assert ch.auto_pick({}, {}) is None
