import os
import celery

app = celery.Celery('example')

app.conf.update(broker_url=os.environ['REDIS_URL'],
                result_backend=os.environ['REDIS_URL'])


@app.task
def add(x, y):
    return x + y
