import random

from app.core.config import settings

FAKE_FCM_SUCCESS_RATE = settings.fake_fcm_success_rate


def fake_fcm_send(token: str, title: str, content: str) -> bool:
    return random.random() < FAKE_FCM_SUCCESS_RATE
