#!/bin/bash
set -e  # Exit immediately if a command exits with a non-zero status

# Function to fetch secrets from AWS Secrets Manager
fetch_secret() {
    local secret_id=$1
    SECRETS=$(aws secretsmanager get-secret-value \
        --secret-id "$secret_id" \
        --query 'SecretString' \
        --output text 2>/dev/null) || {
        echo "Error: Failed to fetch secret $secret_id"
        exit 1
    }
    echo "$SECRETS"
}

# Ensure the service name is passed as an argument
if [ -z "$1" ]; then
    echo "Error: Service name must be passed as the first argument."
    exit 1
fi

SERVICE_NAME=$1
ENV_FILE="./${SERVICE_NAME}.env"

echo "Fetching secrets for service: $SERVICE_NAME..."

# Fetch the secrets
SECRETS=$(fetch_secret "$SERVICE_NAME")
if [ -z "$SECRETS" ]; then
    echo "Error: No secrets retrieved for $SERVICE_NAME"
    exit 1
fi

# Write the secrets into the .env file
echo "Writing secrets to $ENV_FILE..."
echo "# Secrets fetched on $(date)" > "$ENV_FILE"
echo "$SECRETS" | jq -r 'to_entries | .[] | "\(.key)=\(.value)"' >> "$ENV_FILE"

echo "Secrets written to $ENV_FILE."