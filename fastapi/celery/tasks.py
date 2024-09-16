from ocpi22.models.session import Session
from ocpi22.tasks import app as celery_app


@celery_app.task
def activate_session(session: Session):
    print(f'Activating session {session.uid}')
    session.status = 'active'
    session.save()
    session.send_updates()
