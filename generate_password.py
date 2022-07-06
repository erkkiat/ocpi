#!/usr/bin/python

import random

letters = 'zxcbnmkhgfdsaqwertyup23456789'
length = 8
print(''.join(random.choice(letters) for i in range(length)))
