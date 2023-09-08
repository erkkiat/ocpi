from ocpi22.models.session import Session
from ocpi22.tasks import simulate_meter_values


def start_simulated_session(session, token_uid, connector_id, billed_to, evse_uid, response_url=''):
    print(f'Starting session simulator for session {session.uid}')
    args = (session.pk, token_uid, connector_id, billed_to, evse_uid, response_url)
    simulate_meter_values.apply_async(args=args, countdown=5)


def stop_simulated_session(session):
    print(f'Stopping session simulator for session {session.uid}')
    session.status = Session.COMPLETED
    session.save()
    session.send_updates()
