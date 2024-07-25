from ninja import NinjaAPI

from django.conf import settings
from ninja_extra.permissions import IsAdminUser
from ninja_jwt.authentication import JWTAuth
from pymongo import UpdateOne
from rest_framework.decorators import permission_classes
from silk.profiling.profiler import silk_profile
from starlette.exceptions import HTTPException
from starlette.requests import Request

from fastapi.mongodb.connection import tokens_col
from fastapi.schemas.token import TokenSchema, TokenListSchema
from ocpi22.choices import OcpiRolesEnum
from ocpiconnector.ocpi_identities import get_our_party
from util import RedisStore

api = NinjaAPI(urls_namespace='token')
token_store = RedisStore(namespace='tokenallow')


@api.put("/single/", url_name="token-upsert")  # , auth=JWTAuth())
# @permission_classes([IsAdminUser])
async def token_upsert(request: Request, payload: TokenSchema):
    data = payload.dict()  # Convert the payload to a dictionary
    data = fill_token_info(data)
    _id = data.pop('id')  # Use 'id' as the MongoDB '_id'

    result = tokens_col.update_one(
        {'_id': _id},  # Match criteria
        {'$set': data},  # Data to update
        upsert=True  # Insert if no document matches the criteria
    )

    token_store.store(_id, data, expiration=payload.next_update)

    # Check the result to provide appropriate response
    if result.upserted_id:
        status = "inserted"
    elif result.matched_count:
        status = "updated"
    else:
        status = "no changes made"

    return {"status": status}


def fill_token_info(data):
    our_party = get_our_party(OcpiRolesEnum.EMSP)
    data['token'] = dict(
        country_code=our_party.country_code,
        party_id=our_party.party_id,
        type='RFID',
        contract_id='N/A',
        uid=data['id'],
        valid=bool(data['allowed'] == 'ALLOWED'),
        issuer='N/A',
        whitelist='NEVER'
    )
    data.pop('next_update', None)
    return data


@api.put("/list/", url_name="token-list-upsert")
async def bulk_token_upsert(request: Request, payload: TokenListSchema):
    operations = []
    for token in payload.tokens:
        data = token.dict()
        data = fill_token_info(data)
        _id = data.pop('id')  # Use 'id' as the MongoDB '_id'

        operations.append(
            UpdateOne(
                {'_id': _id},  # Match criteria
                {'$set': data},  # Data to update
                upsert=True  # Insert if no document matches the criteria
            )
        )
        token_store.store(_id, data, expiration=token.next_update)

    if operations:
        result = tokens_col.bulk_write(operations)
        return {
            "status": "success",
            "matched_count": result.matched_count,
            "modified_count": result.modified_count,
            "upserted_count": len(result.upserted_ids)
        }
    else:
        raise HTTPException(status_code=400, detail="No tokens to upsert")


@api.post("{token_id}/authorize", url_name="token-authorize")
# @silk_profile(name='token_authorize')
def authorize(request: Request, payload: TokenListSchema, token_id):
    response = token_store.retrieve(token_id)
    return response
