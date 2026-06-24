import pytest
from celery.exceptions import Retry
from unittest.mock import MagicMock

from app.tasks.push import send_push_task


def _make_mock_db(users=None):
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.execute.return_value = MagicMock(
        data=users or []
    )
    mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    return mock_db


def _make_mock_redis(acquired=True):
    mock_redis = MagicMock()
    mock_redis.set.return_value = True if acquired else None
    return mock_redis


@pytest.fixture(autouse=True)
def task_request():
    send_push_task.push_request(retries=0)
    yield
    send_push_task.pop_request()


def test_duplicate_key_returns_early(mocker):
    mock_db = _make_mock_db()

    mocker.patch("app.tasks.push._get_supabase", return_value=mock_db)
    mocker.patch("app.tasks.push._get_redis", return_value=_make_mock_redis(acquired=False))

    send_push_task.run("push_id", "key", "title", "content")

    mock_db.table.assert_not_called()


def test_random_failure_triggers_retry(mocker):
    mock_db = _make_mock_db()
    mock_retry = mocker.patch.object(send_push_task, "retry", side_effect=Retry())

    mocker.patch("app.tasks.push._get_supabase", return_value=mock_db)
    mocker.patch("app.tasks.push._get_redis", return_value=_make_mock_redis())
    mocker.patch("app.tasks.push.random.random", return_value=0.0)

    with pytest.raises(Retry):
        send_push_task.run("push_id", "key", "title", "content")

    mock_retry.assert_called_once()


def test_max_retries_exceeded_sets_dead(mocker):
    send_push_task.pop_request()
    send_push_task.push_request(retries=3)  # max_retries=3 도달

    mock_db = _make_mock_db()
    mock_retry = mocker.patch.object(send_push_task, "retry")

    mocker.patch("app.tasks.push._get_supabase", return_value=mock_db)
    mocker.patch("app.tasks.push._get_redis", return_value=_make_mock_redis())
    mocker.patch("app.tasks.push.random.random", return_value=0.0)

    send_push_task.run("push_id", "key", "title", "content")

    update_calls = str(mock_db.table.return_value.update.call_args_list)
    assert "DEAD" in update_calls
    mock_retry.assert_not_called()


def test_successful_flow_sets_sent(mocker):
    users = [{"id": f"user-{i}", "device_token": f"token-{i}"} for i in range(5)]
    mock_db = _make_mock_db(users=users)

    mocker.patch("app.tasks.push._get_supabase", return_value=mock_db)
    mocker.patch("app.tasks.push._get_redis", return_value=_make_mock_redis())
    mocker.patch("app.tasks.push.random.random", return_value=1.0)
    mocker.patch("app.tasks.push.fake_fcm_send", return_value=True)

    send_push_task.run("push_id", "key", "title", "content")

    update_calls = str(mock_db.table.return_value.update.call_args_list)
    assert "SENT" in update_calls
