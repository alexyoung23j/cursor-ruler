from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from github import Github, GithubIntegration
from dotenv import load_dotenv
import hmac
import hashlib
import logging
import json
import traceback
import uvicorn
import os
from .constants import APP_ID, PRIVATE_KEY, WEBHOOK_SECRET, APPLY_COMMAND, SUMMARY_SIGNATURE, SUGGESTION_SIGNATURE
from .handlers import handle_pr_comment, is_apply_command
from .server_state import get_state_manager, ServerMode, RecentSuggestion, ConnectedRepository
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
logger.info("Environment variables loaded")

# Initialize FastAPI app
app = FastAPI(title="Cursor Rules Bot")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, you might want to limit this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize GitHub App integration if credentials exist
github_integration = None
if all([APP_ID, PRIVATE_KEY, WEBHOOK_SECRET]):
    try:
        github_integration = GithubIntegration(APP_ID, PRIVATE_KEY)
        logger.info("GitHub App integration initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize GitHub App integration: {str(e)}")
else:
    logger.info("GitHub App credentials not found - running in setup mode")

# Add new API models
class ServerModeUpdate(BaseModel):
    is_disabled: Optional[bool] = None
    dry_run: Optional[bool] = None

class RepositoryUpdate(BaseModel):
    enabled: bool

@app.get("/api/state")
async def get_server_state():
    """Get current server state"""
    state_manager = get_state_manager()
    state = state_manager.get_state()
    return {
        "mode": state.mode.model_dump(),
        "repositories": len(state.repositories),
        "recent_suggestions": len(state.recent_suggestions),
        "setup_complete": github_integration is not None
    }

@app.get("/api/suggestions")
async def get_suggestions(repository: Optional[str] = None, limit: int = 50):
    """Get recent suggestions, optionally filtered by repository"""
    if not github_integration:
        raise HTTPException(status_code=503, detail="GitHub App not configured")
    
    state_manager = get_state_manager()
    state = state_manager.get_state()
    
    suggestions = state.recent_suggestions
    if repository:
        suggestions = state.get_recent_suggestions_for_repo(repository)
        
    return {"suggestions": suggestions[-limit:]}

@app.get("/api/repositories")
async def get_repositories():
    """Get list of connected repositories"""
    if not github_integration:
        raise HTTPException(status_code=503, detail="GitHub App not configured")
    
    state_manager = get_state_manager()
    state = state_manager.get_state()
    return {"repositories": list(state.repositories.values())}

@app.patch("/api/mode")
async def update_mode(mode: ServerModeUpdate):
    """Update server operation mode"""
    if not github_integration:
        raise HTTPException(status_code=503, detail="GitHub App not configured")
    
    state_manager = get_state_manager()
    state_manager.set_mode(
        is_disabled=mode.is_disabled,
        dry_run=mode.dry_run
    )
    return {"message": "Mode updated successfully"}

@app.patch("/api/repositories/{full_name:path}")
async def update_repository(full_name: str, update: RepositoryUpdate):
    """Update repository settings"""
    if not github_integration:
        raise HTTPException(status_code=503, detail="GitHub App not configured")
    
    state_manager = get_state_manager()
    state = state_manager.get_state()
    
    if state.set_repository_enabled(full_name, update.enabled):
        state_manager.save_state()
        return {"message": f"Repository {full_name} {'enabled' if update.enabled else 'disabled'}"}
    raise HTTPException(status_code=404, detail="Repository not found")

@app.post("/webhook")
async def webhook(request: Request):
    """Handle GitHub webhook events"""
    if not github_integration:
        raise HTTPException(status_code=503, detail="GitHub App not configured")
    
    logger.info("Received webhook request")

    # Track repository in state
    state_manager = get_state_manager()
    state = state_manager.get_state()

    # Check if server is disabled - do this after repository tracking
    if state.mode.is_disabled:
        logger.info("Server is disabled, skipping webhook processing")
        return {
            "message": "Server is disabled",
            "mode": state.mode.model_dump()
        }
    
    # Verify webhook signature
    signature = request.headers.get("X-Hub-Signature-256")
    if not signature:
        logger.error("Missing webhook signature")
        raise HTTPException(status_code=401, detail="No signature")
    
    body = await request.body()
    logger.debug(f"Webhook body size: {len(body)} bytes")
    
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(signature, expected):
        logger.error("Invalid webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Parse event
    event_type = request.headers.get("X-GitHub-Event")
    if not event_type:
        logger.error("Missing event type header")
        raise HTTPException(status_code=400, detail="No event type")
    
    logger.info(f"Processing {event_type} event")
    data = json.loads(body)
    
    # Get installation token
    installation_id = data["installation"]["id"]
    logger.info(f"Getting token for installation {installation_id}")
    access_token = github_integration.get_access_token(installation_id)
    github_client = Github(access_token.token)
    
    # Get repository info
    repo_name = data["repository"]["full_name"]
    
    # Always track repository activity, even if disabled
    state.update_repository_activity(repo_name)
    
    # Add repository if not seen before (do this even if disabled)
    if repo_name not in state.repositories:
        state.add_repository(ConnectedRepository(
            full_name=repo_name,
            installation_id=installation_id,
            connected_at=datetime.utcnow(),
            last_active=datetime.utcnow(),
            enabled=True  # New repositories are enabled by default
        ))
        state_manager.save_state()
    
    # Check if repository is enabled
    if not state.is_repository_enabled(repo_name):
        logger.info(f"Repository {repo_name} is disabled, skipping webhook processing")
        return {
            "message": "Repository is disabled",
            "repository": repo_name
        }
    
    # Process the event based on type
    try:
        if event_type == "pull_request_review_comment" or event_type == "issue_comment":
            logger.info(f"Processing {event_type} on {repo_name}")
            
            # Skip if the action is not 'created'
            if data.get("action") != "created":
                logger.info(f"Ignoring {event_type} with action '{data.get('action')}'")
                return {"message": f"Ignoring {data.get('action')} action"}
            
            # Extract PR number based on event type
            if event_type == "pull_request_review_comment":
                pr_number = data["pull_request"]["number"]
            else:  # issue_comment
                # For issue comments, we need to check if it's on a PR
                if "pull_request" not in data["issue"]:
                    logger.info("Ignoring issue comment not on a PR")
                    return {"message": "Comment is not on a PR"}
                pr_number = data["issue"]["number"]
            
            # Process the comment with dry run mode if enabled
            result = await handle_pr_comment(github_client, data, dry_run=state.mode.dry_run)
            
            # If in dry run mode, add mode info to response
            if state.mode.dry_run:
                result = {
                    **result,
                    "mode": state.mode.model_dump()
                }
            
            return result
        
        logger.info(f"Ignoring unsupported event type: {event_type}")
        return {"message": f"Event type {event_type} not handled"}
    
    except Exception as e:
        logger.error(f"Error processing webhook: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/setup-status")
async def get_setup_status():
    """Check if all required environment variables are set"""
    # Check if either OpenAI or Anthropic API key is set
    has_llm_key = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"))
    
    # Only check for base64 private key
    has_private_key = bool(os.getenv("GITHUB_PRIVATE_KEY_BASE64"))
    
    required_vars = {
        "LLM_API_KEY": has_llm_key,  # Either ANTHROPIC_API_KEY or OPENAI_API_KEY
        "GITHUB_APP_ID": bool(APP_ID),
        "GITHUB_PRIVATE_KEY_BASE64": has_private_key,  # Only use GITHUB_PRIVATE_KEY_BASE64
        "WEBHOOK_SECRET": bool(WEBHOOK_SECRET)
    }
    
    all_configured = all(required_vars.values())
    
    return {
        "configured": all_configured,
        "variables": required_vars,
        "setup_complete": github_integration is not None
    }

# Mount frontend static files if they exist - MOVED TO END OF FILE
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "out")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

if __name__ == "__main__":
    logger.info("Starting Cursor Rules Bot server...")
    uvicorn.run(app, host="0.0.0.0", port=8000) 