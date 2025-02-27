# Cursor Ruler

Cursor Ruler is a self-hosted Github App that uses your team's PR comments and feedback to generate and manage Cursor rules files, turning Cursor into a collaborative force multiplier for your entire engineering team. 3 Minutes from `git clone` to production—give it a try!

![Screenshot 2025-02-24 at 6 35 25 PM](https://github.com/user-attachments/assets/f7f6d41d-9c4b-49b0-a7ac-037e42a328ba)

## What Are Cursor Rules?

Cursor rules are instructions that customize AI behavior in the Cursor. They function as specialized system prompts for the underlying language models, helping to control how AI responds in different contexts:

- **Project Rules**: Stored in the `.cursor/rules` directory, these provide granular control with file pattern matching using glob patterns
- **Semantic Descriptions**: Each rule includes a description of when it should be applied
- **Automatic Attachment**: Rules can be automatically included when matching files are referenced

Cursor Ruler helps teams collaboratively develop these rules by capturing best practices and repository-specific instructions from PR comments, turning them into a cohesive set of rules that improve AI interactions across your codebase. **This transforms Cursor from a powerful individual developer tool into a collaborative force multiplier for your entire engineering team.**

## How It Works

Cursor Ruler streamlines the process of creating and managing Cursor rules through GitHub pull requests:

1. **Automatic Analysis**: The bot monitors PR comments and uses either Anthropic or OpenAI (based on your provided API key) to identify comments that could potentially be used as Cursor rules.

2. **Rule Generation**: When a relevant comment is detected, the bot uses an LLM to generate an appropriate Cursor rule and posts a suggestion as a reply to the original comment.

   - Rules are currently generated according to the best practices outlined [here](https://forum.cursor.com/t/my-best-practices-for-mdc-rules-and-troubleshooting/50526)
   - These are subject to change, and the bot will need to be updated to reflect new best practices as these emerge.

3. **Review Process**: The suggestion includes a diff showing the proposed changes to existing rules or creation of new rule files.

4. **Acceptance Workflow**: Team members can click an "Accept" button on suggestions they want to implement. The bot aggregates all accepted suggestions into a summary comment on the PR.

5. **Finalization**: When ready, a team member can comment with the command `/apply-cursor-rules` to trigger the bot to commit all accepted changes to the PR. After this commit, the bot stops analyzing further comments on that PR.

6. **Management Interface**: A web-based frontend allows you to:

   - View recent suggestions and their statuses
   - Disable the bot globally or for specific repositories
   - Enable "dry-run" mode to preview bot actions without making actual comments or commits

   The frontend uses a simple file-based state management system that is not persistent and is only meant to display recent data for ease of use. It provides a lightweight way to monitor and control the bot's activities without requiring a complex database setup.

This workflow helps teams collaboratively develop and maintain Cursor rules while keeping the process integrated with your normal code review workflow. By aggregating collective best practices and repository-specific instructions from PR discussions, Cursor Ruler helps build a comprehensive set of rules that improve AI assistance throughout your development process.

## Google Cloud Run Deployment

### First-time setup:

1. **Clone the repository**:

```bash
# Open Google Cloud Shell
# Clone the repository
git clone https://github.com/alexyoung23j/cursor-ruler.git
cd cursor-ruler

# Note: If you have two-factor authentication enabled, you may need to use a personal access token instead:
# git clone https://YOUR_USERNAME:YOUR_PERSONAL_ACCESS_TOKEN@github.com/alexyoung23j/cursor-ruler.git
# You can create a personal access token at: https://github.com/settings/tokens
```

2. **Enable required APIs** (run in Google Cloud Shell):

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com
```

3. **Create Docker repository** (run in Google Cloud Shell):

```bash
gcloud artifacts repositories create cursor-ruler \
  --repository-format=docker \
  --location=us-east1
```

4. **Build and deploy** (run in Google Cloud Shell):

```bash
# Set your Google Cloud project ID
export PROJECT_ID=$(gcloud config get-value project)

# Build the container
gcloud builds submit . --tag us-east1-docker.pkg.dev/$PROJECT_ID/cursor-ruler/app

# Deploy to Cloud Run
gcloud run deploy cursor-ruler \
  --image us-east1-docker.pkg.dev/$PROJECT_ID/cursor-ruler/app \
  --platform managed \
  --region us-east1 \
  --allow-unauthenticated \
  --port 8000
```

5. After deployment, you'll get a URL like `https://cursor-ruler-xxxxx.run.app` - you'll need this for the GitHub App setup. Your deployment should appear in the Cloud Run dashboard.

## GitHub App Setup

Now that you have your Cloud Run service running, you can set up the GitHub App:

1. **Create a GitHub App**:

   - Go to your GitHub profile settings → Developer settings → GitHub Apps → New GitHub App
   - Fill in the required fields:

     - **Name**: Cursor Rules Bot (or your preferred name)
     - **Homepage URL**: Your Cloud Run URL (from step 4 above)
     - **Webhook URL**: Your Cloud Run URL + `/webhook` (e.g., `https://cursor-rules-xxxxx.run.app/webhook`)
     - **Webhook Secret**: Generate a secure random string (at least 32 characters). You can generate one by running:
       ```bash
       # In your terminal
       openssl rand -hex 32
       ```
       Save this value - you'll need it for the `WEBHOOK_SECRET` environment variable.

   - **Permissions**:
     - Repository permissions:
       - Contents: Read & write
       - Pull requests: Read & write
       - Issues: Read & write
     - Organization permissions:
       - Members: Read-only
     - Subscribe to events:
       - Issue comment
       - Pull request review comment

2. **Generate a Private Key**:

   - After creating the app, scroll down and click "Generate a private key"
   - Download the key file (it will be a .pem file)
   - Format the key for use in environment variables:
     ```bash
     python scripts/format_private_key.py /path/to/your-private-key.pem
     ```
   - Copy the base64-encoded output - you'll need this for the `GITHUB_PRIVATE_KEY_BASE64` environment variable

3. **Install the App**:

   - Click "Install App" in the sidebar
   - Choose the repositories where you want to use the bot

4. (Optional) Give the app a profile picture (it will default to the Github User who set it up if you don't)

## Configure Environment Variables

After setting up both Cloud Run and the GitHub App, you'll need to configure these environment variables in Cloud Run. These values can be found in the settings page for the Github App:

**Required Variables:**

- `GITHUB_APP_ID` - Your GitHub App's ID
- `GITHUB_PRIVATE_KEY_BASE64` - Base64-encoded version of your github app private key (.pem file)
  - Use the included helper script to generate this:
    ```bash
    python scripts/format_private_key.py /path/to/your-private-key.pem
    ```
- `WEBHOOK_SECRET` - The webhook secret you created during GitHub App setup (must be a secure random string)
- **LLM API Key** (at least one of these is required):
  - `ANTHROPIC_API_KEY` - Your Anthropic API key (recommended)
  - `OPENAI_API_KEY` - Your OpenAI API key

After setting these variables, visit the Cloud Run url to access the frontend. The app is now live!

## Updating the App

When you want to update the app with new code changes, (run in Google Cloud Shell):

```bash
# Navigate to your repository directory
cd cursor-ruler

# Pull latest code
git pull

# Build and deploy new version
export PROJECT_ID=$(gcloud config get-value project)
gcloud builds submit . --tag us-east1-docker.pkg.dev/$PROJECT_ID/cursor-ruler/app && \
gcloud run deploy cursor-ruler \
  --image us-east1-docker.pkg.dev/$PROJECT_ID/cursor-ruler/app \
  --platform managed \
  --region us-east1 \
  --allow-unauthenticated \
  --port 8000
```

## Local Development

1. **Set up Python environment**:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. **Start the servers**:

```bash
# Start backend (in one terminal)
just start-backend

# Start frontend (in another terminal)
just start-frontend
```

3. **Using ngrok for local webhook testing**:

If you want to test the GitHub webhook integration locally, you can use ngrok to create a public URL that forwards to your local server:

```bash
# Install ngrok if you haven't already
brew install ngrok  # on macOS
# or download from https://ngrok.com/download

# Start ngrok (after your backend is running)
ngrok http --url=<your-ngrok-url> 8000
```

Use the ngrok URL (e.g., `https://your-tunnel.ngrok-free.app`) as your GitHub App's webhook URL during local development.

## Testing

Cursor Ruler includes a test suite to ensure the bot functions correctly. The tests are organized into several categories that validate different aspects of the application:

### Running Tests

All tests can be run using the `just` command runner. Here are the main testing commands:

```bash
# Run all tests
just test

# List all available test cases with their numbers
just list-cases
```

### Test Categories

The test suite covers several key areas of functionality:

1. **Rule Generation Prompt Tests**: Validate that the bot correctly identifies comments that should be turned into rules and generates appropriate rule content.

```bash
# Run a specific prompt test case
just test-prompts-case <test_case_number>
```

2. **Format Suggestion Tests**: Ensure that suggestion comments are properly formatted with the correct diff and UI elements.

```bash
# Run all format suggestion tests
just test-format

# Run a specific format suggestion test case
just test-format-case <n>
```

3. **Merge Tests**: Verify that multiple rule suggestions can be correctly merged without conflicts.

```bash
# Run all merge tests
just test-merges

# List available merge test cases
just list-merge-cases

# Run a specific merge test case
just test-merge-case <case_name>
```

4. **Apply Tests**: Test the functionality that applies accepted changes to the repository.

```bash
# Run a specific apply test case
just test-apply-case <case_name>
```

Test cases are defined in YAML files in the `tests/test_cases` directory, with merge test cases in `tests/merge_test_cases`. These test definitions include sample PR comments, expected rule outputs, and other test parameters.

### Common Issues

1. **Webhook 500 Internal Server Error**:

   - Ensure your `WEBHOOK_SECRET` is a secure random string (use `openssl rand -hex 32` to generate one)
   - Make sure the webhook secret in GitHub App settings matches the `WEBHOOK_SECRET` environment variable
   - Check that your GitHub private key is properly formatted (see below)

2. **GitHub Authentication Issues**:

   - Make sure you're using the base64-encoded private key
   - Run `python scripts/format_private_key.py /path/to/your-private-key.pem`
   - Copy the output exactly and set it as `GITHUB_PRIVATE_KEY_BASE64` in Cloud Run
   - Do not modify the encoded string in any way

3. **No Rule Suggestions Generated**:
   - Verify that your LLM API key is valid and has not expired
   - Check the Cloud Run logs for any errors related to the LLM service
   - Ensure your GitHub App has the correct permissions and webhook events configured
