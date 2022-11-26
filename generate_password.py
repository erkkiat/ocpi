#!/usr/bin/python

import random

letters = 'zxcbnmkhgfdsaqwertyupZXCBNMKHGFDSAQWERTYUP23456789!#%/?+-'
length = 12
print(''.join(random.choice(letters) for i in range(length)))
