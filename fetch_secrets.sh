#!/bin/bash
set -e

# Fetch secrets from AWS Secrets Manager
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

# Ensure the AWS_SECRET_ID is set
if [ -z "$AWS_SECRET_ID" ]; then
    echo "Error: AWS_SECRET_ID environment variable is not set."
    exit 1
fi

echo "Fetching secrets for $AWS_SECRET_ID..."

# Fetch the secrets and export them as environment variables
SECRETS=$(fetch_secret "$AWS_SECRET_ID")
if [ -z "$SECRETS" ]; then
    echo "Error: No secrets retrieved for $AWS_SECRET_ID"
    exit 1
fi

# Export secrets without using a temporary file
echo "$SECRETS" | jq -r 'to_entries | .[] | "export \(.key)=\(.value)"' | while read -r line; do
    eval "$line"
done

echo "Secrets fetched and exported for $AWS_SECRET_ID."

# Execute the main command
exec "$@"
