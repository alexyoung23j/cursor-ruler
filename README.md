# Cursor Ruler

Cursor Ruler is a self-hosted Github App that uses your team's PR comments and feedback to generate and manage Cursor rules files, turning Cursor into a collaborative force multiplier for your entire engineering team. 3 Minutes from `git clone` to production—give it a try!

![Screenshot 2025-02-24 at 6 35 25 PM](https://github.com/user-attachments/assets/f7f6d41d-9c4b-49b0-a7ac-037e42a328ba)

Watch a quick [demo](https://youtu.be/2RRaN0Gg-3Q).

## What Are Cursor Rules?

Cursor rules are instructions that customize AI behavior in the Cursor. They function as specialized system prompts for the underlying language models, helping to control how AI responds in different contexts:

- **Project Rules**: Stored in the `.cursor/rules` directory, these provide granular control with file pattern matching using glob patterns
- **Semantic Descriptions**: Each rule includes a description of when it should be applied
- **Automatic Attachment**: Rules can be automatically included when matching files are referenced

Cursor Ruler helps teams collaboratively develop these rules by capturing best practices and repository-specific instructions from PR comments, turning them into a cohesive set of rules that improve AI interactions across your codebase. **This transforms Cursor from a powerful individual developer tool into a collaborative force multiplier for your entire engineering team.**

## How It Works

Cursor Ruler streamlines the process of creating and managing Cursor rules through GitHub pull requests:

1. **Automatic Analysis**: The bot monitors PR comments and uses Anthropic's Claude to identify comments that could potentially be used as Cursor rules.

2. **Rule Generation**: When a relevant comment is detected, the bot uses an LLM to generate an appropriate Cursor rule and posts a suggestion as a reply to the original comment.

   - Rules are currently generated according to the best practices outlined [here](https://forum.cursor.com/t/my-best-practices-for-mdc-rules-and-troubleshooting/50526)
   - These are subject to change, and the bot will need to be updated to reflect new best practices as these emerge.
   - Rules are generated in the following general format, based on suggestions from the Cursor Community. The bot will try to follow these file naming and concept grouping guidelines:
     - 001-099: Core/foundational rules
     - 100-199: Integration/API rules
     - 200-299: Pattern/role-specific rules
     - 300-399: Testing/QA rules
   - IMPORTANT: If you have no existing rules, the bot will always place any suggestions in a first rule file called `001-core-standards.mdc`. We recommend adding a few basic rules to your repo before enabling this bot for the first time for best possible results. Rules should be fairly small and focused.

3. **Review Process**: The suggestion includes a diff showing the proposed changes to existing rules or creation of new rule files.

4. **Acceptance Workflow**: Team members can click an "Accept" button on suggestions they want to implement. The bot aggregates all accepted suggestions into a summary comment on the PR.

5. **Finalization**: When ready, a team member can comment with the command `/apply-cursor-rules` to trigger the bot to commit all accepted changes to the PR. After this commit, the bot stops analyzing further comments on that PR.

6. **Management Interface**: A web-based frontend allows you to:

   - View recent suggestions and their statuses
   - Disable the bot globally or for specific repositories
   - Enable "dry-run" mode to preview bot actions without making actual comments or commits

   The frontend uses a state management system that persists configuration and recent activity in your chosen storage backend (Cloud Storage, S3, Azure Blob Storage, or local files). This ensures your settings and bot state are preserved across deployments and container restarts.

This workflow helps teams collaboratively develop and maintain Cursor rules while keeping the process integrated with your normal code review workflow. By aggregating collective best practices and repository-specific instructions from PR discussions, Cursor Ruler helps build a comprehensive set of rules that improve AI assistance throughout your development process.

## Deployment

### Google Cloud Run Deployment

The instructions below are for deploying to Google Cloud Run, but since Cursor Ruler is containerized with Docker, you can deploy it to any platform that supports Docker containers. The key requirements are:

1. A platform that can run the Docker container (defined in `Dockerfile`)
2. Exposing port 8000 for the application
3. Setting the required environment variables:
   - `GITHUB_APP_ID`
   - `GITHUB_PRIVATE_KEY_BASE64`
   - `WEBHOOK_SECRET`
   - `ANTHROPIC_API_KEY`
   - `STORAGE_URL` and associated storage credentials
4. Persistent storage configuration:
   - For Cloud Run: Follow the GCS setup instructions below
   - For AWS: Configure S3 bucket and AWS credentials
   - For Azure: Configure Blob Storage and connection string
   - For persistent servers: Ensure the local file path is writable

For other platforms like AWS, Azure, DigitalOcean, etc, you'll follow their specific instructions for deploying Docker containers while ensuring these requirements are met.

### First-time setup:

1. **Clone the repository**:

```bash
# Open Google Cloud Shell Terminal
git clone https://github.com/alexyoung23j/cursor-ruler.git
cd cursor-ruler
```

2. **Enable required APIs** (run in Google Cloud Shell):

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  storage.googleapis.com
```

3. **Set up Cloud Storage for persistent state**:

```bash
# Set your Google Cloud project ID
export PROJECT_ID=$(gcloud config get-value project)

# Create a bucket for storing state
gsutil mb -l us-east1 gs://$PROJECT_ID-cursor-ruler-state

# Create a service account for accessing the bucket
gcloud iam service-accounts create cursor-ruler-sa \
    --display-name="Cursor Ruler Service Account"

# Grant the service account full object access (create, read, update, delete)
gsutil iam ch \
    serviceAccount:cursor-ruler-sa@$PROJECT_ID.iam.gserviceaccount.com:roles/storage.objectAdmin \
    gs://$PROJECT_ID-cursor-ruler-state
```

4. **Create Docker repository** (run in Google Cloud Shell):

```bash
gcloud artifacts repositories create cursor-ruler \
  --repository-format=docker \
  --location=us-east1
```

5. **Build and deploy** (run in Google Cloud Shell):

```bash
# Build the container
gcloud builds submit . --tag us-east1-docker.pkg.dev/$PROJECT_ID/cursor-ruler/app

# Deploy to Cloud Run with storage configuration
gcloud run deploy cursor-ruler \
  --image us-east1-docker.pkg.dev/$PROJECT_ID/cursor-ruler/app \
  --platform managed \
  --region us-east1 \
  --allow-unauthenticated \
  --port 8000 \
  --service-account cursor-ruler-sa@$PROJECT_ID.iam.gserviceaccount.com \
  --set-env-vars "STORAGE_URL=gs://$PROJECT_ID-cursor-ruler-state/state.json" \
  --min-instances=1  # Prevents cold starts and maintains state
```

6. After deployment, you'll get a URL like `https://cursor-ruler-xxxxx.run.app` - you'll need this for the GitHub App setup. Your deployment should appear in the Cloud Run dashboard.

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

Don't worry, the bot will never make any commits without your explicit approval!

2. **Generate a Private Key**:

   - After creating the app, scroll down and click "Generate a private key"
   - Download the key file (it will be a .pem file)
   - Format the key for use in environment variables (either upload the pem file to cloud console in the cursor-ruler root or download the repo locally and run the script):
     ```bash
     python scripts/format_private_key.py /path/to/your-private-key.pem
     ```
   - Copy the base64-encoded output - you'll need this for the `GITHUB_PRIVATE_KEY_BASE64` environment variable

3. **Install the App**:

   - Click "Install App" in the sidebar
   - Choose the repositories where you want to use the bot

4. (Optional) Give the app a profile picture (it will default to the Github User who set it up if you don't)

## Configure Environment Variables

After setting up both Cloud Run and the GitHub App, you'll need to configure these environment variables in Cloud Run. It is easiest to do this with the Cloud Console UI, search for "Cloud Run" and you should see the cursor-ruler service.

**Required Variables:**

- `GITHUB_APP_ID` - Your GitHub App's ID (accessed from the Github App settings page)
- `GITHUB_PRIVATE_KEY_BASE64` - Base64-encoded version of your github app private key (.pem file), generated in step 2
- `WEBHOOK_SECRET` - The webhook secret you created during GitHub App setup (must be a secure random string)
- `ANTHROPIC_API_KEY` - Your Anthropic API key

After setting these variables, visit the Cloud Run url to access the frontend. The app is now live!

The app will be automatically started in "Dry Run" mode, so it will not actually make any comments or commits but will still run rule generation code and allow you to see suggestions in the frontend. Use this to verify the app is generating rules that you approve of. The Dry Run mode can be toggled on and off in the frontend.

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

Updating the app will reset the app to "Dry Run" mode (and remove all the ephemeral logs from the frontend).

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
   - Verify that your Anthropic API key is valid and has not expired
   - Check the Cloud Run logs for any errors related to the LLM service
   - Ensure your GitHub App has the correct permissions and webhook events configured
