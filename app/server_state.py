from typing import List, Dict, Optional, Literal
from pydantic import BaseModel
import json
import os
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

class RecentSuggestion(BaseModel):
    """A recent suggestion made by the bot"""
    id: str  # Unique ID for the suggestion
    repository: str  # Full repository name (owner/repo)
    pr_number: int  # PR number
    file_path: str  # Path of the file being modified
    timestamp: datetime  # When the suggestion was made
    status: Literal["suggested", "pending", "accepted", "rejected", "applied", "dry_run"]  # Current status
    suggestion_text: str  # The actual suggestion text
    comment_url: Optional[str] = None  # URL to the GitHub comment
    is_dry_run: bool = False  # Whether this was generated in dry run mode
    dry_run_preview: Optional[dict] = None  # Preview of what would have been done in dry run mode
    thread_root_id: Optional[int] = None  # ID of the root comment in the thread
    
class ConnectedRepository(BaseModel):
    """Information about a repository connected to the bot"""
    full_name: str  # Full repository name (owner/repo)
    installation_id: int  # GitHub App installation ID
    connected_at: datetime  # When the repository was connected
    last_active: datetime  # Last time we saw activity from this repo
    enabled: bool = True  # Whether the bot should process this repository

class ServerMode(BaseModel):
    """Current operation mode of the server"""
    is_disabled: bool = False  # If True, bot does nothing
    dry_run: bool = True  # If True, bot processes but doesn't make changes
    
class ServerState(BaseModel):
    """Global server state"""
    mode: ServerMode = ServerMode()
    repositories: Dict[str, ConnectedRepository] = {}  # Keyed by full_name
    recent_suggestions: List[RecentSuggestion] = []
    max_suggestions_history: int = 250  # Maximum number of suggestions to keep
    
    def add_suggestion(self, suggestion: RecentSuggestion) -> None:
        """Add a new suggestion to the history"""
        # For dry runs, mark the suggestion appropriately
        if suggestion.is_dry_run:
            suggestion.status = "dry_run"
        
        self.recent_suggestions.append(suggestion)
        # Trim history if needed
        if len(self.recent_suggestions) > self.max_suggestions_history:
            self.recent_suggestions = self.recent_suggestions[-self.max_suggestions_history:]
            
    def update_suggestion_status(self, suggestion_id: str, status: str) -> None:
        """Update the status of a suggestion"""
        for suggestion in self.recent_suggestions:
            if suggestion.id == suggestion_id:
                # Don't update status of dry run suggestions
                if not suggestion.is_dry_run:
                    suggestion.status = status
                break
                
    def add_repository(self, repo: ConnectedRepository) -> None:
        """Add or update a connected repository"""
        self.repositories[repo.full_name] = repo
        
    def update_repository_activity(self, full_name: str) -> None:
        """Update the last_active timestamp for a repository"""
        if full_name in self.repositories:
            self.repositories[full_name].last_active = datetime.utcnow()
            
    def get_repository(self, full_name: str) -> Optional[ConnectedRepository]:
        """Get repository info by full name"""
        return self.repositories.get(full_name)
        
    def get_recent_suggestions_for_repo(self, full_name: str) -> List[RecentSuggestion]:
        """Get recent suggestions for a specific repository"""
        return [s for s in self.recent_suggestions if s.repository == full_name]
        
    def set_repository_enabled(self, full_name: str, enabled: bool) -> bool:
        """Enable or disable a repository. Returns True if successful."""
        if full_name in self.repositories:
            self.repositories[full_name].enabled = enabled
            return True
        return False

    def is_repository_enabled(self, full_name: str) -> bool:
        """Check if a repository is enabled"""
        repo = self.repositories.get(full_name)
        return repo is not None and repo.enabled

class StateManager:
    """Manages the server state persistence"""
    def __init__(self, state_file: str = "data/server_state.json"):
        self.state_file = state_file
        self.state = self._load_state()
        
    def _load_state(self) -> ServerState:
        """Load state from file or create new if doesn't exist"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    return ServerState.model_validate(data)
        except Exception as e:
            logger.error(f"Failed to load state file: {e}")
        return ServerState()
        
    def save_state(self) -> None:
        """Save current state to file"""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            
            with open(self.state_file, 'w') as f:
                json.dump(self.state.model_dump(), f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save state file: {e}")
            
    def get_state(self) -> ServerState:
        """Get the current server state"""
        return self.state
        
    def set_mode(self, is_disabled: bool = None, dry_run: bool = None) -> None:
        """Update server operation mode"""
        if is_disabled is not None:
            self.state.mode.is_disabled = is_disabled
        if dry_run is not None:
            self.state.mode.dry_run = dry_run
        self.save_state()
        
# Global state manager instance
_state_manager: Optional[StateManager] = None

def get_state_manager(state_file: str = "data/server_state.json") -> StateManager:
    """Get the global state manager instance"""
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager(state_file)
    return _state_manager 