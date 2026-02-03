# ONEagent

AI-powered Slack bot that provisions Coder workspaces on demand.

## Overview

ONEagent allows developers to request development workspaces directly from Slack using natural language:

```
@ONEagent onboard backend dev for repo vinod-itmethods/coder-sq-demo
```

The bot uses AWS Bedrock (Claude) to understand the request and automatically:
1. Identifies the GitHub repository
2. Detects the appropriate template (Java, Python, TypeScript)
3. Creates a Coder workspace
4. Responds with the workspace URL

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐     ┌─────────────┐
│   Slack     │────▶│ API Gateway │────▶│  Lambda         │────▶│   Coder     │
│  @ONEagent  │     │             │     │  (Python)       │     │   API       │
└─────────────┘     └─────────────┘     └────────┬────────┘     └─────────────┘
                                                 │
                                    ┌────────────┼────────────┐
                                    ▼            ▼            ▼
                              ┌──────────┐ ┌──────────┐ ┌──────────┐
                              │ Bedrock  │ │ Secrets  │ │ GitHub   │
                              │ Claude   │ │ Manager  │ │ API      │
                              └──────────┘ └──────────┘ └──────────┘
```

## Features

- **Natural Language Processing**: Understands various phrasings
  - "onboard backend dev for repo X"
  - "create workspace for frontend developer with repo Y"
  - "spin up Java environment for repo Z"

- **Auto-Detection**: Infers template from repository language if not specified

- **Templates**: Supports Java, Python, and TypeScript workspaces

- **Thread Replies**: Responds in Slack threads for clean conversation flow

## Project Structure

```
oneagent/
├── lambda/
│   ├── handler.py           # Lambda entry point
│   ├── slack_client.py      # Slack API client
│   ├── bedrock_client.py    # AWS Bedrock/Claude client
│   ├── coder_client.py      # Coder API client
│   ├── github_client.py     # GitHub API client
│   └── requirements.txt     # Python dependencies
├── coder-templates/
│   ├── java/main.tf         # Java workspace template
│   ├── python/main.tf       # Python workspace template
│   └── typescript/main.tf   # TypeScript workspace template
├── docs/
│   └── AWS_SETUP.md         # Detailed AWS setup guide
└── README.md
```

## Quick Start

### Prerequisites

- AWS Account with Bedrock access
- Coder instance (self-hosted or cloud)
- Slack workspace (admin access)
- GitHub account

### Setup

1. **Clone this repository**
   ```bash
   git clone https://github.com/vinod-itmethods/oneagent.git
   cd oneagent
   ```

2. **Follow the AWS Setup Guide**
   See [docs/AWS_SETUP.md](docs/AWS_SETUP.md) for detailed instructions.

3. **Push Coder Templates**
   ```bash
   coder login https://your-coder-instance.com
   cd coder-templates/java && coder templates push java
   cd ../python && coder templates push python
   cd ../typescript && coder templates push typescript
   ```

4. **Test in Slack**
   ```
   @ONEagent onboard dev for repo octocat/Hello-World
   ```

## Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `AWS_REGION` | AWS region for Bedrock (default: us-east-1) |
| `BEDROCK_MODEL_ID` | Claude model ID |

### Secrets (AWS Secrets Manager)

| Secret | Description |
|--------|-------------|
| `oneagent/slack-bot-token` | Slack Bot OAuth Token |
| `oneagent/slack-signing-secret` | Slack Signing Secret |
| `oneagent/coder-api-token` | Coder API Token |
| `oneagent/coder-url` | Coder instance URL |
| `oneagent/github-token` | GitHub PAT |

## Usage Examples

```
# Basic usage
@ONEagent onboard dev for repo owner/repo-name

# Specify template
@ONEagent create java workspace for repo owner/java-project

# Specify developer type
@ONEagent onboard frontend developer for repo owner/react-app

# With branch
@ONEagent spin up workspace for repo owner/repo branch feature-x
```

## Coder Templates

### Java Template
- OpenJDK 11/17/21
- Maven & Gradle pre-installed
- Auto-detects pom.xml or build.gradle

### Python Template
- Python 3.10/3.11/3.12
- uv package manager
- Auto-installs from pyproject.toml or requirements.txt

### TypeScript Template
- Node.js 18/20/22
- npm, pnpm, yarn, bun support
- Auto-detects package manager

## Development

### Local Testing

```bash
cd lambda
pip install -r requirements.txt

# Test intent extraction
python -c "
from bedrock_client import BedrockClient
client = BedrockClient()
print(client.extract_intent('onboard backend dev for repo octocat/Hello-World'))
"
```

### Deploy Updates

```bash
cd lambda
pip install -r requirements.txt -t .
zip -r ../oneagent-lambda.zip .
aws lambda update-function-code \
  --function-name oneagent \
  --zip-file fileb://../oneagent-lambda.zip
```

## Troubleshooting

See [docs/AWS_SETUP.md#troubleshooting](docs/AWS_SETUP.md#troubleshooting)

## License

MIT
