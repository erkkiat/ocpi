from functools import cache


class MyClass:
    def __init__(self, value):
        self.value = value

    def __hash__(self):
        return hash(self.value)

    def __eq__(self, other):
        return self.value == other.value

    def doit(self):
        print('doit called')
        self.value += 1


@cache
def my_func(m: MyClass):
    print('my_func called')
    return m.value + 1


m = MyClass(5)
print(f'{hash(m)=}')
print(my_func(m))
print(my_func(m))
print(my_func(m))
print(my_func(m))
m.doit()
print(my_func(m))
print(my_func(m))
print(my_func(m))
print(my_func(m))
