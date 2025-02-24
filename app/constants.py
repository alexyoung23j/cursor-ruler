import os
import base64
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

# Bot signatures
SUMMARY_SIGNATURE = "### 💡 CURSOR RULE SUGGESTIONS SUMMARY"
SUGGESTION_SIGNATURE = "**💡 CURSOR RULE SUGGESTION**"
APPLIED_SIGNATURE = "✅ RULES APPLIED"

# Commands
APPLY_COMMAND = "/apply-cursor-rules"  # Command to apply suggestions

# GitHub specific
BOT_APP_NAME = "cursor-rules-bot[bot]" # TODO: make this an env var i think

# Environment variables
APP_ID = os.getenv("GITHUB_APP_ID")

# Only use the base64-encoded private key
PRIVATE_KEY_BASE64 = os.getenv("GITHUB_PRIVATE_KEY_BASE64")
PRIVATE_KEY = None

# Decode the base64 private key
if PRIVATE_KEY_BASE64:
    try:
        PRIVATE_KEY = base64.b64decode(PRIVATE_KEY_BASE64).decode('utf-8')
    except Exception as e:
        print(f"Error decoding base64 private key: {e}")

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET") 