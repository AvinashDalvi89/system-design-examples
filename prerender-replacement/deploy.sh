#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy.sh — One-time setup + deploy for nushiftconnect prerender renderer
#
# Run this once to set everything up. After that, re-deploying is just:
#   docker build → docker push → aws lambda update-function-code
# ─────────────────────────────────────────────────────────────────────────────
set -e

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION="ap-south-1"
LAMBDA_NAME="nushiftconnect-renderer"
S3_BUCKET="nushiftconnect-prerender-cache"
ECR_REPO="nushiftconnect-renderer"
INTERNAL_TOKEN=$(openssl rand -hex 32)  # Generated once — save this value!

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "AWS Account : $AWS_ACCOUNT_ID"
echo "Region      : $AWS_REGION"
echo "INTERNAL_TOKEN: $INTERNAL_TOKEN"
echo "  ↑ Copy this token into lambda-edge.js INTERNAL_TOKEN constant"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── STEP 1: S3 Bucket for cache ───────────────────────────────────────────────
echo ""
echo "Step 1: Creating S3 cache bucket..."
aws s3api create-bucket \
  --bucket $S3_BUCKET \
  --region $AWS_REGION \
  --create-bucket-configuration LocationConstraint=$AWS_REGION

# Block all public access (cache is private, Lambda reads/writes directly)
aws s3api put-public-access-block \
  --bucket $S3_BUCKET \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

echo "S3 bucket created: $S3_BUCKET"

# ── STEP 2: ECR Repository ────────────────────────────────────────────────────
echo ""
echo "Step 2: Creating ECR repository..."
aws ecr create-repository \
  --repository-name $ECR_REPO \
  --region $AWS_REGION \
  --image-scanning-configuration scanOnPush=false \
  2>/dev/null || echo "ECR repo already exists, continuing..."

ECR_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO"

# ── STEP 3: Build and push Docker image ───────────────────────────────────────
echo ""
echo "Step 3: Building Docker image (first build takes ~3-5 minutes for npm install)..."
cd renderer-lambda

aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

docker build --platform linux/amd64 --provenance=false -t $ECR_REPO:latest .
docker tag $ECR_REPO:latest "$ECR_URI:latest"
docker push "$ECR_URI:latest"

IMAGE_URI="$ECR_URI:latest"
echo "Image pushed: $IMAGE_URI"
cd ..

# ── STEP 4: IAM Role for Lambda ───────────────────────────────────────────────
echo ""
echo "Step 4: Creating IAM role..."
ROLE_NAME="nushiftconnect-renderer-role"

aws iam create-role \
  --role-name $ROLE_NAME \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }]
  }' 2>/dev/null || echo "Role already exists, continuing..."

# Attach policy
aws iam put-role-policy \
  --role-name $ROLE_NAME \
  --policy-name prerender-renderer-policy \
  --policy-document file://iam-policy.json

ROLE_ARN="arn:aws:iam::$AWS_ACCOUNT_ID:role/$ROLE_NAME"
echo "IAM role: $ROLE_ARN"

# Wait for role to propagate
echo "Waiting 10s for IAM role propagation..."
sleep 10

# ── STEP 5: Create Lambda function ────────────────────────────────────────────
echo ""
echo "Step 5: Creating Lambda function..."
aws lambda create-function \
  --function-name $LAMBDA_NAME \
  --region $AWS_REGION \
  --package-type Image \
  --code ImageUri=$IMAGE_URI \
  --role $ROLE_ARN \
  --memory-size 2048 \
  --timeout 30 \
  --environment "Variables={
    CACHE_BUCKET=$S3_BUCKET,
    CACHE_TTL_HOURS=24,
    INTERNAL_TOKEN=$INTERNAL_TOKEN
  }" 2>/dev/null || {
    echo "Function exists — updating code and config..."
    aws lambda update-function-code \
      --function-name $LAMBDA_NAME \
      --region $AWS_REGION \
      --image-uri $IMAGE_URI
    aws lambda update-function-configuration \
      --function-name $LAMBDA_NAME \
      --region $AWS_REGION \
      --memory-size 2048 \
      --timeout 30 \
      --environment "Variables={
        CACHE_BUCKET=$S3_BUCKET,
        CACHE_TTL_HOURS=24,
        INTERNAL_TOKEN=$INTERNAL_TOKEN
      }"
  }

# Wait for function to be active
echo "Waiting for Lambda to become active..."
aws lambda wait function-active --function-name $LAMBDA_NAME --region $AWS_REGION

# ── STEP 6: Create Lambda Function URL ───────────────────────────────────────
echo ""
echo "Step 6: Creating Lambda Function URL..."
FUNCTION_URL=$(aws lambda create-function-url-config \
  --function-name $LAMBDA_NAME \
  --region $AWS_REGION \
  --auth-type NONE \
  --query FunctionUrl \
  --output text 2>/dev/null || \
  aws lambda get-function-url-config \
    --function-name $LAMBDA_NAME \
    --region $AWS_REGION \
    --query FunctionUrl \
    --output text)

# Allow public invoke via Function URL
aws lambda add-permission \
  --function-name $LAMBDA_NAME \
  --region $AWS_REGION \
  --statement-id FunctionURLAllowPublicAccess \
  --action lambda:InvokeFunctionUrl \
  --principal '*' \
  --function-url-auth-type NONE \
  2>/dev/null || true

LAMBDA_HOST=$(echo $FUNCTION_URL | sed 's|https://||' | sed 's|/||')

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ DEPLOYMENT COMPLETE"
echo ""
echo "Lambda Function URL host:"
echo "  $LAMBDA_HOST"
echo ""
echo "Now update lambda-edge.js:"
echo "  1. Set INTERNAL_TOKEN = '$INTERNAL_TOKEN'"
echo "  2. Set domainName = '$LAMBDA_HOST'"
echo ""
echo "Then redeploy Lambda@Edge to CloudFront."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── STEP 7: Smoke test ────────────────────────────────────────────────────────
echo ""
echo "Smoke test (WhatsApp bot UA against your homepage)..."
curl -s -o /dev/null -w "HTTP %{http_code} in %{time_total}s\n" \
  -H "User-Agent: WhatsApp/2.23.1 A" \
  -H "X-Internal-Token: $INTERNAL_TOKEN" \
  "${FUNCTION_URL}"
