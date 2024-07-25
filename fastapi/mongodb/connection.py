import pymongo

client = pymongo.MongoClient("mongodb://ocpi:ocpiocpi@localhost:27017/")
ocpidb = client.ocpi221
meter_values_col = ocpidb.meter_values
tokens_col = ocpidb.tokens
