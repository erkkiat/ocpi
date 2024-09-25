documentation = dict(
    INVOICING="""
This is where you tell the system where to send the invoicing records (Charge Detail Records).

{{flowchart}}

## URL Segments
Example URL: `https://your.emsp.backend.server/invoicing/{{cdr_id}}/`. The variable will be substituted with
the corresponding parameter from the data sent to this URL.

## Basic Authentication
Include the user credentials and port of your endpoint in the URL,
for example `https://user:password@example.com:1234/path/to/my/endpoint/`.

## Status codes
* `HTTP_200_OK` when the webhook was set successfully
* `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
    """,
    TOKEN_AUTH="""
When an RFID issued by you is tapped on a charger, this webhook will be called to authorize the token.

{{flowchart}}

### URL Segments
Example URL: `https://your.emsp.backend.server/authorize/{{token_id}}/`. The token_id will be substituted with
the corresponding parameter from the data sent to this URL.

### Status Codes
* `HTTP_200_OK` when the webhook was set successfully
* `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
    """,
    SESSION="""
This is where you tell the system where to send Session updates.

{{flowchart}}

### URL Segments
Example URL: `https://your.emsp.backend.server/session/{{session_id}}/`. The session_id will be substituted with
the corresponding parameter from the data sent to this URL.

### Status Codes
* `HTTP_200_OK` when the webhook was set successfully
* `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
    """,
    CP_STATUS="""
This is where you tell the system where to send charge point status updates.
When a charge point changes status, the system pushes the new status to your webhook URL.

{{flowchart}}

## URL Segments
Example URL: `https://your.emsp.backend.server/authorize/{token_id}/`. The token_id will be substituted with
the corresponding parameter from the data sent to this URL.

## Status Codes
* `HTTP_200_OK` when the webhook was set successfully
* `HTTP_400_BAD_REQUEST` when the request is not formatted in the required way
    """,
)

common_documentation = """
### Basic Authentication
Include the user credentials and port of your endpoint in the URL,
for example `https://user:password@example.com:1234/path/to/my/endpoint/`.

### Webhook Data
Click "OPTIONS" to see what data is sent to you through the webhook 
and what data is expected from you in the response.
"""
