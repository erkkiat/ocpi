import pytest
from celery.schedules import crontab


class TestRedbeatConfiguration:
    @pytest.fixture
    def celery_app(self):
        from ocpi22.tasks import app

        return app

    def test_beat_scheduler_is_redbeat(self, celery_app):
        assert celery_app.conf.beat_scheduler == "redbeat.RedBeatScheduler"

    def test_redbeat_redis_url_is_configured(self, celery_app):
        assert celery_app.conf.redbeat_redis_url is not None

    def test_redbeat_lock_timeout_is_300_seconds(self, celery_app):
        assert celery_app.conf.redbeat_lock_timeout == 300

    def test_redbeat_key_prefix_is_configured(self, celery_app):
        assert celery_app.conf.redbeat_key_prefix == "redbeat:"


class TestBeatScheduleConfiguration:
    @pytest.fixture
    def celery_app(self):
        from ocpi22.tasks import app

        return app

    @pytest.fixture
    def beat_schedule(self, celery_app):
        return celery_app.conf.beat_schedule

    def test_beat_schedule_contains_celery_heartbeat_task(self, beat_schedule):
        assert "run-me-every-minute" in beat_schedule
        assert (
            beat_schedule["run-me-every-minute"]["task"]
            == "ocpi22.tasks.celery_heartbeat"
        )

    def test_beat_schedule_contains_still_alive_task(self, beat_schedule):
        assert "still-alive" in beat_schedule
        assert beat_schedule["still-alive"]["task"] == "ocpi22.tasks.check_still_alive"

    def test_beat_schedule_contains_pull_all_objects_task(self, beat_schedule):
        assert "pull-all-objects" in beat_schedule
        assert (
            beat_schedule["pull-all-objects"]["task"] == "ocpi22.tasks.pull_all_objects"
        )

    def test_beat_schedule_contains_hubject_evse_full_load_task(self, beat_schedule):
        assert "weekly-hubject-evse-full-load" in beat_schedule
        assert (
            beat_schedule["weekly-hubject-evse-full-load"]["task"]
            == "ocpi22.tasks.send_hubject_evse_full_load"
        )

    def test_celery_heartbeat_task_schedule_is_3600_seconds(self, beat_schedule):
        assert beat_schedule["run-me-every-minute"]["schedule"] == 3600

    def test_hubject_evse_full_load_runs_on_sunday(self, beat_schedule):
        schedule = beat_schedule["weekly-hubject-evse-full-load"]["schedule"]
        assert isinstance(schedule, crontab)
        assert schedule.day_of_week == {0}

    def test_hubject_evse_full_load_runs_at_2am(self, beat_schedule):
        schedule = beat_schedule["weekly-hubject-evse-full-load"]["schedule"]
        assert isinstance(schedule, crontab)
        assert schedule.hour == {2}
        assert schedule.minute == {0}

    def test_pull_all_objects_schedule_is_crontab(self, beat_schedule):
        schedule = beat_schedule["pull-all-objects"]["schedule"]
        assert isinstance(schedule, crontab)

    def test_pull_all_objects_runs_between_0_and_3_hour(self, beat_schedule):
        schedule = beat_schedule["pull-all-objects"]["schedule"]
        hour_value = list(schedule.hour)[0]
        assert 0 <= hour_value <= 3
