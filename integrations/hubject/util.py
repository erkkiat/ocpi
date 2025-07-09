def decode_country_code_and_party_id(provider_id: str) -> tuple[str | None, str | None]:
    if provider_id is None:
        return None, None
    if "*" in provider_id:
        return tuple(provider_id.split("*"))
    elif "-" in provider_id:
        return tuple(provider_id.split("-"))
    elif len(provider_id) == 5 and provider_id.isalnum():
        # Assuming the format is 'CCPPP' where CC is country code and PPP is party ID
        return provider_id[:2], provider_id[2:]
    else:
        raise ValueError(f"Invalid ProviderID format: {provider_id}")
