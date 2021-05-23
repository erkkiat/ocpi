from django.db import models


class Token(models.Model):
    """
    A Token structure with data owned by the eMSP
    """

    # ISO-3166 alpha-2 country code of the MSP that 'owns' this Token
    country_code = models.CharField(max_length=2)

    # CPO ID of the MSP that 'owns' this Token (following the ISO-15118)
    party_id = models.CharField(max_length=3)

    # Unique ID by which this Token can be identified.
    # This is the field used by CPO system (RFID reader on the Charge Point) to identify this token.
    # Currently, in most cases: type=RFID, this is the RFID hidden ID as read by the RFID reader, but that is not a requirement.
    # If this is a APP_USER or AD_HOC_USER Token, it will be a uniquely, by the eMSP, generated ID.
    # This field is named uid instead of id to prevent confusion with: contract_id.
    uid = models.CharField(max_length=36)

    TYPE_CHOICES = (
        ('AD_HOC_USER', 'Ad hoc user'),
        ('APP_USER', 'Application user'),
        ('OTHER', 'Other'),
        ('RFID', 'RFID tag'),
    )
    type = models.CharField(max_length=11, choices=TYPE_CHOICES)

    # Uniquely identifies the EV Driver contract token within the eMSP’s platform (and suboperator platforms).
    # Recommended to follow the specification for eMA ID from
    # "eMI3 standard version V1.0" (http://emi3group.com/documents-links/) "Part 2: business objects."
    contract_id = models.CharField(max_length=36)

    # Visual readable number/identification as printed on the Token (RFID card), might be equal to the contract_id.
    visual_number = models.CharField(max_length=64, null=True, blank=True)

    # Issuing company, most of the times the name of the company printed on the token (RFID card),
    # not necessarily the eMSP.
    issuer = models.CharField(max_length=64)

    # This ID groups a couple of tokens. This can be used to make two or more tokens work as one,
    # so that a session can be started with one token and stopped with another, handy when a card and key-fob
    # are given to the EV-driver. Beware that OCPP 1.5/1.6 only support group_ids
    # (it is called parentId in OCPP 1.5/1.6) with a maximum length of 20.
    group_id = models.CharField(max_length=36, null=True, blank=True)

    valid = models.BooleanField()

    WHITELIST_CHOICES = (
        # Token always has to be whitelisted, realtime authorization is not possible/allowed.
        # CPO shall always allow any use of this Token.
        ('ALWAYS', 'Always'),

        # It is allowed to whitelist the token, realtime authorization is also allowed.
        # The CPO may choose which version of authorization to use.
        ('ALLOWED', 'Allowed'),

        # In normal situations realtime authorization shall be used. But when the CPO cannot get a response
        # from the eMSP (communication between CPO and eMSP is offline), the CPO shall allow this Token to be used.
        ('ALLOWED_OFFLINE', 'Allowed when offline'),

        # Whitelisting is forbidden, only realtime authorization is allowed. CPO shall always send
        # a realtime authorization for any use of this Token to the eMSP.
        ('NEVER', 'Never, only real time'),
    )
    whitelist = models.CharField(max_length=15, choices=WHITELIST_CHOICES)

    # Language Code ISO 639-1. This optional field indicates the Token owner’s preferred interface language.
    # If the language is not provided or not supported then the CPO is free to choose its own language.
    language = models.CharField(max_length=2, null=True, blank=True)

    # The default Charging Preference. When this is provided, and a charging session is started on
    # an Charge Point that support Preference base Smart Charging and support this ProfileType,
    # the Charge Point can start using this ProfileType, without this having to be set via: Set Charging Preferences.
    PROFILE_TYPE_CHOICES = (
        ('CHEAP', 'Cheap charging'),  # Driver wants to use the cheapest charging profile possible.
        ('FAST', 'Fast charging'),  # Driver wants his EV charged as quickly as possible and is willing to pay a premium for this.
        ('GREEN', 'Green energy'),  # Driver wants his EV charged with as much regenerative (green) energy as possible.
        ('REGULAR', 'Regular, no preference'),  # Driver does not have special preferences.
    )
    default_profile_type = models.CharField(max_length=7, null=True, blank=True, choices=PROFILE_TYPE_CHOICES)

    # energy_contract = models.CharField(max_length=80)  # No type documentation available

    # Timestamp when this Token was last updated (or created).
    last_updated = models.DateTimeField(auto_now_add=True)


class AuthorizationInfo(models.Model):

    # Status of the Token, and whether charging is allowed at the optionally given location.
    ALLOWED_CHOICES = (
        ('ALLOWED', 'Allowed'),
        ('BLOCKED', 'Blocked'),
        ('EXPIRED', 'Expired token'),
        ('NO_CREDIT', 'User has ho credit'),
        ('NOT_ALLOWED', 'Not allowed'),
    )
    allowed = models.CharField(max_length=11, choices=ALLOWED_CHOICES)

    # The complete Token object for which this authorization was requested.
    token = models.ForeignKey(Token, on_delete=models.PROTECT)

    # Optional reference to the location if it was included in the request, and if the EV driver is allowed
    # to charge at that location. Only the EVSEs the EV driver is allowed to charge at are returned.
    # location = models.ForeignKey(Location, on_delete=models.PROTECT)

    # Reference to the authorization given by the eMSP, when given, this reference will be provided
    # in the relevant Session and/or CDR.
    authorization_reference = models.CharField(max_length=36)
