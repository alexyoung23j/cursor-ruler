from typing import List, Dict, Optional, Literal, Protocol, runtime_checkable
from pydantic import BaseModel
import json
import os
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import base64

# Optional storage backend imports - imported on demand
storage_backends = {
    'gcs': False,
    's3': False,
    'azure': False
}

try:
    from google.cloud import storage
    storage_backends['gcs'] = True
except ImportError:
    pass

try:
    import boto3
    storage_backends['s3'] = True
except ImportError:
    pass

try:
    from azure.storage.blob import BlobServiceClient
    storage_backends['azure'] = True
except ImportError:
    pass

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

@runtime_checkable
class StorageBackend(Protocol):
    """Abstract interface for storage backends"""
    def read(self) -> Optional[str]:
        """Read state from storage, return None if doesn't exist"""
        ...
    
    def write(self, data: str) -> None:
        """Write state to storage"""
        ...

class LocalFileStorage(StorageBackend):
    """Local file storage implementation"""
    def __init__(self, path: str):
        self.path = Path(path)
        
    def read(self) -> Optional[str]:
        try:
            if self.path.exists():
                return self.path.read_text()
            return None
        except Exception as e:
            logger.error(f"Failed to read from local file: {e}")
            return None
            
    def write(self, data: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(data)
        except Exception as e:
            logger.error(f"Failed to write to local file: {e}")

class GoogleCloudStorage(StorageBackend):
    """Google Cloud Storage implementation"""
    def __init__(self, bucket: str, path: str):
        try:
            self.client = storage.Client()
            self.bucket = self.client.bucket(bucket)
            self.blob = self.bucket.blob(path.lstrip('/'))
        except ImportError:
            raise ImportError("google-cloud-storage is required for GCS storage")
            
    def read(self) -> Optional[str]:
        try:
            if self.blob.exists():
                return self.blob.download_as_text()
            return None
        except Exception as e:
            logger.error(f"Failed to read from GCS: {e}")
            return None
            
    def write(self, data: str) -> None:
        try:
            self.blob.upload_from_string(data)
        except Exception as e:
            logger.error(f"Failed to write to GCS: {e}")

class S3Storage(StorageBackend):
    """AWS S3 Storage implementation"""
    def __init__(self, bucket: str, path: str):
        try:
            self.s3 = boto3.client('s3')
            self.bucket = bucket
            self.key = path.lstrip('/')
        except ImportError:
            raise ImportError("boto3 is required for S3 storage")
            
    def read(self) -> Optional[str]:
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=self.key)
            return response['Body'].read().decode('utf-8')
        except self.s3.exceptions.NoSuchKey:
            return None
        except Exception as e:
            logger.error(f"Failed to read from S3: {e}")
            return None
            
    def write(self, data: str) -> None:
        try:
            self.s3.put_object(Bucket=self.bucket, Key=self.key, Body=data.encode('utf-8'))
        except Exception as e:
            logger.error(f"Failed to write to S3: {e}")

class AzureStorage(StorageBackend):
    """Azure Blob Storage implementation"""
    def __init__(self, container: str, path: str):
        try:
            connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
            if not connection_string:
                raise ValueError("AZURE_STORAGE_CONNECTION_STRING environment variable is required")
            self.service_client = BlobServiceClient.from_connection_string(connection_string)
            self.container_client = self.service_client.get_container_client(container)
            self.blob_client = self.container_client.get_blob_client(path.lstrip('/'))
        except ImportError:
            raise ImportError("azure-storage-blob is required for Azure storage")
            
    def read(self) -> Optional[str]:
        try:
            return self.blob_client.download_blob().readall().decode('utf-8')
        except Exception as e:
            if 'BlobNotFound' in str(e):
                return None
            logger.error(f"Failed to read from Azure: {e}")
            return None
            
    def write(self, data: str) -> None:
        try:
            self.blob_client.upload_blob(data, overwrite=True)
        except Exception as e:
            logger.error(f"Failed to write to Azure: {e}")

def get_storage_backend(url: str) -> StorageBackend:
    """Create appropriate storage backend from URL"""
    parsed = urlparse(url)
    scheme = parsed.scheme
    
    if scheme == 'file':
        path = parsed.netloc + parsed.path
        return LocalFileStorage(path)
    elif scheme == 'gs':
        return GoogleCloudStorage(parsed.netloc, parsed.path)
    elif scheme == 's3':
        return S3Storage(parsed.netloc, parsed.path)
    elif scheme == 'az':
        return AzureStorage(parsed.netloc, parsed.path)
    else:
        raise ValueError(f"Unsupported storage scheme: {scheme}")

class StateManager:
    """Manages the server state persistence"""
    def __init__(self, storage_url: Optional[str] = None):
        if storage_url is None:
            storage_url = os.getenv('STORAGE_URL', 'file://data/server_state.json')
        
        self.storage = get_storage_backend(storage_url)
        self.state = self._load_state()
        
    def _load_state(self) -> ServerState:
        """Load state from storage or create new if doesn't exist"""
        try:
            data = self.storage.read()
            if data:
                return ServerState.model_validate(json.loads(data))
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
        return ServerState()
        
    def save_state(self) -> None:
        """Save current state to storage"""
        try:
            data = json.dumps(self.state.model_dump(), indent=2, default=str)
            self.storage.write(data)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
            
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

def get_state_manager(storage_url: Optional[str] = None) -> StateManager:
    """Get the global state manager instance"""
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager(storage_url)
    return _state_manager 