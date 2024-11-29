#!/bin/bash
set -e

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

# Ensure the AWS_SECRET_ID environment variable is set
if [ -z "$AWS_SECRET_ID" ]; then
    echo "Error: AWS_SECRET_ID environment variable is not set."
    exit 1
fi

echo "Fetching secrets for $AWS_SECRET_ID..."

# Fetch the secrets
SECRETS=$(fetch_secret "$AWS_SECRET_ID")
if [ -z "$SECRETS" ]; then
    echo "Error: No secrets retrieved for $AWS_SECRET_ID"
    exit 1
fi

# Write the secrets into /etc/environment and export them
echo "$SECRETS" | jq -r 'to_entries | .[] | "\(.key)=\(.value)"' | while read -r line; do
    # Append the secret to /etc/environment
    echo "$line" >> /etc/environment
    # Export the secret as an environment variable for immediate use
    eval "export $line"
done

echo "Secrets written to /etc/environment and exported to the current environment."

# Execute the main command
exec "$@"
