import time


class Timer:
    interval = 0.0

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        self.end = time.time()
        self.interval = self.end - self.start

    def __float__(self):
        return self.interval

    def __repr__(self):
        return str(self.interval)
