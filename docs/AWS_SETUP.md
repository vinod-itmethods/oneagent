# AWS Setup Guide for ONEagent

This guide walks through setting up the AWS infrastructure for ONEagent.

## Prerequisites

- AWS Account with admin access
- AWS CLI configured (`aws configure`)
- Slack workspace admin access
- Coder instance running
- GitHub account

## Architecture Overview

```
Slack → API Gateway → Lambda → Bedrock/Coder/GitHub
```

## Step 1: Create Slack App

1. Go to [Slack API Apps](https://api.slack.com/apps)
2. Click **Create New App** → **From scratch**
3. Name: `ONEagent`, select your workspace

### Configure OAuth & Permissions

1. Go to **OAuth & Permissions**
2. Add Bot Token Scopes:
   - `app_mentions:read`
   - `chat:write`
   - `users:read`
3. Click **Install to Workspace**
4. Copy the **Bot User OAuth Token** (starts with `xoxb-`)

### Configure Event Subscriptions

1. Go to **Event Subscriptions**
2. Enable Events: **On**
3. Request URL: `https://YOUR_API_GATEWAY_URL/slack/events` (set after creating API Gateway)
4. Subscribe to bot events:
   - `app_mention`
5. Save Changes

### Get Signing Secret

1. Go to **Basic Information**
2. Copy the **Signing Secret**

## Step 2: Create AWS Secrets

Store secrets in AWS Secrets Manager:

```bash
# Slack Bot Token
aws secretsmanager create-secret \
  --name oneagent/slack-bot-token \
  --secret-string "xoxb-your-token-here"

# Slack Signing Secret
aws secretsmanager create-secret \
  --name oneagent/slack-signing-secret \
  --secret-string "your-signing-secret"

# Coder API Token (generate from Coder UI: User Settings → Tokens)
aws secretsmanager create-secret \
  --name oneagent/coder-api-token \
  --secret-string "your-coder-token"

# Coder URL
aws secretsmanager create-secret \
  --name oneagent/coder-url \
  --secret-string "https://coder.your-company.com"

# GitHub Token (create at github.com/settings/tokens)
aws secretsmanager create-secret \
  --name oneagent/github-token \
  --secret-string "ghp_your-token"
```

## Step 3: Create IAM Role for Lambda

```bash
# Create trust policy
cat > trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Create role
aws iam create-role \
  --role-name oneagent-lambda-role \
  --assume-role-policy-document file://trust-policy.json

# Create permissions policy
cat > permissions-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:*:*:secret:oneagent/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.*"
    }
  ]
}
EOF

# Attach policy
aws iam put-role-policy \
  --role-name oneagent-lambda-role \
  --policy-name oneagent-permissions \
  --policy-document file://permissions-policy.json
```

## Step 4: Create Lambda Function

### Package the code

```bash
cd lambda
pip install -r requirements.txt -t .
zip -r ../oneagent-lambda.zip .
cd ..
```

### Create Lambda function

```bash
aws lambda create-function \
  --function-name oneagent \
  --runtime python3.11 \
  --role arn:aws:iam::YOUR_ACCOUNT_ID:role/oneagent-lambda-role \
  --handler handler.lambda_handler \
  --zip-file fileb://oneagent-lambda.zip \
  --timeout 30 \
  --memory-size 256 \
  --environment "Variables={AWS_REGION=us-east-1,BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0}"
```

### Add environment variables for secrets

Instead of hardcoding, fetch from Secrets Manager in code. Add a helper:

```python
# Add to handler.py
import boto3

def get_secret(secret_name):
    client = boto3.client('secretsmanager')
    response = client.get_secret_value(SecretId=secret_name)
    return response['SecretString']
```

## Step 5: Create API Gateway

```bash
# Create HTTP API
aws apigatewayv2 create-api \
  --name oneagent-api \
  --protocol-type HTTP \
  --target arn:aws:lambda:us-east-1:YOUR_ACCOUNT_ID:function:oneagent

# Get the API endpoint
aws apigatewayv2 get-apis --query "Items[?Name=='oneagent-api'].ApiEndpoint" --output text
```

### Add Lambda permission for API Gateway

```bash
aws lambda add-permission \
  --function-name oneagent \
  --statement-id apigateway-invoke \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:us-east-1:YOUR_ACCOUNT_ID:API_ID/*"
```

## Step 6: Update Slack Event URL

1. Go back to your Slack app → **Event Subscriptions**
2. Set Request URL to: `https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/slack/events`
3. Slack will send a verification challenge
4. Save once verified

## Step 7: Push Coder Templates

Upload templates to your Coder instance:

```bash
# Login to Coder
coder login https://coder.your-company.com

# Push templates
cd coder-templates/java
coder templates push java

cd ../python
coder templates push python

cd ../typescript
coder templates push typescript
```

## Step 8: Test the Integration

1. Go to any Slack channel where ONEagent is installed
2. Type: `@ONEagent onboard backend dev for repo octocat/Hello-World`
3. The bot should respond with a workspace URL

## Troubleshooting

### Check Lambda Logs

```bash
aws logs tail /aws/lambda/oneagent --follow
```

### Test Lambda Locally

```bash
# Create test event
cat > test-event.json << 'EOF'
{
  "body": "{\"type\":\"event_callback\",\"event\":{\"type\":\"app_mention\",\"text\":\"<@BOTID> onboard dev for repo octocat/Hello-World\",\"channel\":\"C123\",\"user\":\"U456\",\"ts\":\"1234567890.123456\"}}",
  "headers": {
    "x-slack-request-timestamp": "1234567890",
    "x-slack-signature": "v0=test"
  }
}
EOF

# Invoke locally (skip signature validation for testing)
aws lambda invoke \
  --function-name oneagent \
  --payload file://test-event.json \
  response.json
```

### Common Issues

| Issue | Solution |
|-------|----------|
| "Invalid signature" | Check `SLACK_SIGNING_SECRET` |
| "Repository not found" | Check GitHub token permissions |
| "Template not found" | Push templates to Coder first |
| Bedrock access denied | Enable Claude model in Bedrock console |

## Security Considerations

1. **Secrets**: Never commit tokens to git
2. **API Gateway**: Consider adding API key or AWS WAF
3. **Lambda**: Use VPC if Coder is in private network
4. **Slack**: Verify request signatures (already implemented)

## Cost Estimate

| Service | Estimated Monthly Cost |
|---------|----------------------|
| Lambda | ~$1 (1000 requests/month) |
| API Gateway | ~$1 |
| Secrets Manager | ~$2 (5 secrets) |
| Bedrock | ~$10 (1000 requests) |
| **Total** | **~$14/month** |
