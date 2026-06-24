import app.services.fake_fcm as fake_fcm_module
from app.services.fake_fcm import fake_fcm_send


def test_always_success(monkeypatch):
    monkeypatch.setattr(fake_fcm_module, "FAKE_FCM_SUCCESS_RATE", 1.0)
    assert fake_fcm_send("token", "title", "content") is True


def test_always_fail(monkeypatch):
    monkeypatch.setattr(fake_fcm_module, "FAKE_FCM_SUCCESS_RATE", 0.0)
    assert fake_fcm_send("token", "title", "content") is False
