import os


def export_environment_variables(_request):
    return dict(
        country_code=os.environ.get('COUNTRY_CODE'),
        party_id=os.environ.get('PARTY_ID'),
        header_color=os.environ.get('HEADER_COLOR'),
    )
