import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from functools import wraps

import pytz
from django.utils.datetime_safe import datetime
from rest_framework import status

from ocpi22.choices import OcpiModuleEnum
from util import RedisStore
from ocpiconnector import settings

certification_step_list = defaultdict(list)
persistent_storage = RedisStore(namespace='certify')


@dataclass
class CertificationStep:
    topic: str
    action: str
    description: str
    customer_initiates: bool
    subtopic: str
    result_reported: bool = field(default=False)
    result: bool = field(default=None)
    passed_at: datetime = field(default=None)

    def __bool__(self):
        return self.result_reported and self.result

    def passed(self, reason='OK', result=True):
        from ocpi22 import logging as logging
        logging.info(
            f'Certification step {self.topic} / {self.action} {"succeeded" if result else "failed"}: {reason}'
        )
        self.result_reported = True
        self.result = result
        self.passed_at = datetime.utcnow().replace(tzinfo=pytz.utc)
        self.store()

    def failed(self, reason='No details available'):
        self.passed(reason=reason, result=False)

    def store(self):
        global persistent_storage
        fields = ('result_reported', 'result', 'passed_at')
        data = {x: getattr(self, x) for x in fields}
        persistent_storage[hash(self)] = data

    def retrieve(self):
        try:
            global persistent_storage
            data = persistent_storage[hash(self)]
            self.__dict__.update(data)
            self.passed_at = datetime.fromisoformat(data['passed_at'])
        except KeyError:
            pass

    def __hash__(self):
        key = f'{self.topic}{self.action}'
        hexdata = hashlib.md5(str(key).encode()).hexdigest()
        return int(hexdata, 16)


def register_certification_step(topic, action: str, description: str = None,
                                customer_initiates: bool = True, subtopic: str = None):
    """Register a certification step so that we can show the certification progress to the user"""

    global certification_step_list
    if isinstance(topic, OcpiModuleEnum):
        topic = topic.value
    # print(f'*** Registering certification_step: {topic=} {action=} {description=} {customer_initiates=}')
    step = CertificationStep(topic, action, description, customer_initiates, subtopic)
    certification_step_list[topic].append(step)
    return step


def certification_step(topic, action: str, description: str = None,
                       customer_initiates: bool = True, subtopic: str = None):
    """
    Decorator which notes the response from each action
    so that we can track and show the certification progress to the user
    """

    if settings.CERTIFICATION_MODE:
        step = register_certification_step(topic, action, description, customer_initiates, subtopic)
    else:
        return lambda func: func

    @wraps(certification_step)
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            kwargs['certification'] = step
            ocpi_response = func(*args, **kwargs)
            if not settings.CERTIFICATION_MODE:
                return ocpi_response
            success = ocpi_response is True or \
                getattr(ocpi_response, 'status_code', None) in {status.HTTP_200_OK, status.HTTP_201_CREATED}
            step.passed(result=success)
            return ocpi_response
        return wrapper
    return decorator
