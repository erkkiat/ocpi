from celery import Celery
from icecream import ic

app = Celery('tasks')
app.config_from_object('ocpi22.celeryconfig')


@app.task
def add(x, y):
    result = dict(
        input=(x, y),
        result=x + y
    )
    ic(result)
    return result


@app.task
def command_start():
    pass
