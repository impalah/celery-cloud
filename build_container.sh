#!/bin/bash

# Declare variables
PROFILE="pak"
DOMAIN="celery-cloud"
DOMAIN_OWNER="670089840758"
AWS_REGION="eu-west-1"
REGISTRY_URI="670089840758.dkr.ecr.eu-west-1.amazonaws.com"
REPOSITORY_NAME="lambda-runner"
BASE_VERSION="0.1.1"
PLATFORM="linux/amd64"
# PLATFORM="linux/amd64,linux/arm64"
BUILDER_NAME="mybuilder"


while [[ "$#" -gt 0 ]]; do
    case $1 in
        --repository_name) REPOSITORY_NAME="$2"; shift ;;
        --base_version) BASE_VERSION="$2"; shift ;;
        --platform) PLATFORM="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

# Verify if builder exists
if docker buildx ls | grep -q "^$BUILDER_NAME "; then
    echo "✅ Builder '$BUILDER_NAME' exists. Activating ..."
    docker buildx use "$BUILDER_NAME"
    echo "✅ Builder '$BUILDER_NAME' active."

else
    echo "⚠️  Builder '$BUILDER_NAME' not found. Creating..."
    docker buildx create --name "$BUILDER_NAME" --use
    echo "✅ Builder '$BUILDER_NAME' created and active."
fi


set -e

docker buildx inspect $BUILDER_NAME --bootstrap

# echo "Authorizing in codeartifact"
# export CODEARTIFACT_AUTH_TOKEN=$(aws --profile $PROFILE codeartifact get-authorization-token --region $AWS_REGION --domain $CODE_ARTIFACT_DOMAIN --domain-owner $DOMAIN_OWNER --query authorizationToken --output text)

echo "Authorizing in repo"
aws --profile $PROFILE ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $REGISTRY_URI

echo "$REGISTRY_URI/$DOMAIN/$REPOSITORY_NAME:$BASE_VERSION"


echo "Installing QEMU for multi-architecture support"
docker run --rm --privileged 654654400302.dkr.ecr.eu-west-1.amazonaws.com/multiarch/qemu-user-static --reset -p yes

echo "Creating secret files for CodeArtifact"
echo -n "$CODEARTIFACT_AUTH_TOKEN" > /tmp/codeartifact_auth_token
echo -n "aws" > /tmp/codeartifact_username

echo "Building the image for multiple platforms"
docker buildx build --progress=plain --platform $PLATFORM --secret id=codeartifact_auth_token,src=/tmp/codeartifact_auth_token --secret id=codeartifact_username,src=/tmp/codeartifact_username -t $REGISTRY_URI/$DOMAIN/$REPOSITORY_NAME:$BASE_VERSION -f Dockerfile --push .

# docker buildx imagetools create -t $REGISTRY_URI/$REPOSITORY_NAME:$BASE_VERSION

docker buildx rm $BUILDER_NAME
