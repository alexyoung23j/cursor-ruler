import os
import logging
import base64
from typing import Dict, List, Optional
from github import Github, Repository, GithubException
from github.GithubException import RateLimitExceededException
import time
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class CursorRule(BaseModel):
    """Represents a single Cursor rule file"""
    name: str
    description: str
    globs: List[str]
    content: str
    file_path: str

def get_rules_directory() -> str:
    """Get the path to the cursor rules directory"""
    return ".cursor/rules"

def parse_rule_content(content: str, file_path: str) -> Optional[CursorRule]:
    """Parse rule content from a .mdc file"""
    try:
        # Extract name from filepath
        name = os.path.splitext(os.path.basename(file_path))[0]
        
        # Parse description and globs from content
        description = ""
        globs = []
        
        lines = content.split('\n')
        for line in lines:
            if line.startswith('description:'):
                description = line.replace('description:', '').strip()
            elif line.startswith('globs:'):
                globs_str = line.replace('globs:', '').strip()
                globs = [g.strip() for g in globs_str.split(',') if g.strip()]
        
        return CursorRule(
            name=f"{name}.mdc",
            description=description,
            globs=globs,
            content=content,
            file_path=file_path
        )
    except Exception as e:
        logger.error(f"Failed to parse rule file {file_path}: {str(e)}")
        return None

def get_contents_with_retry(repo: Repository, path: str, ref: str = None, max_retries: int = 3) -> Optional[List]:
    """Get contents from GitHub with rate limit handling and retries"""
    for attempt in range(max_retries):
        try:
            contents = repo.get_contents(path, ref=ref)
            return contents if isinstance(contents, list) else [contents]
        except RateLimitExceededException as e:
            reset_time = repo.rate_limiting_resettime
            wait_time = reset_time - int(time.time())
            if wait_time > 0 and attempt < max_retries - 1:
                logger.warning(f"Rate limit exceeded. Waiting {wait_time} seconds...")
                time.sleep(min(wait_time + 1, 300))  # Wait at most 5 minutes
            else:
                raise
        except GithubException as e:
            if e.status == 404:  # Not found is okay, just return None
                return None
            logger.error(f"GitHub API error: {str(e)}")
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)  # Exponential backoff
    return None

def get_current_rules(repo: Repository, ref: str = None) -> List[CursorRule]:
    """Get all current cursor rules in the repository using GitHub API
    
    Args:
        repo: The GitHub repository object
        ref: The branch/commit reference to fetch from (e.g., PR head branch)
    """
    rules = []
    
    try:
        # Only check .cursor/rules directory as that's the only valid location
        rules_dir = get_rules_directory()
        dir_contents = get_contents_with_retry(repo, rules_dir, ref=ref)
        
        if dir_contents:
            for content in dir_contents:
                if content.path.endswith('.mdc'):
                    try:
                        file_content = base64.b64decode(content.content).decode('utf-8')
                        rule = parse_rule_content(file_content, content.path)
                        if rule:
                            rules.append(rule)
                    except Exception as e:
                        logger.error(f"Error processing rule file {content.path}: {str(e)}")
                        continue
        else:
            logger.info("No .cursor/rules directory found")
                    
    except Exception as e:
        logger.error(f"Error fetching rules from repository: {str(e)}")
        if isinstance(e, RateLimitExceededException):
            logger.error(f"Rate limit exceeded. Reset time: {repo.rate_limiting_resettime}")
        raise
        
    return rules

def format_rules_for_llm(rules: List[CursorRule]) -> str:
    """Format cursor rules in a way that's easy for the LLM to understand"""
    if not rules:
        return "No existing Cursor rules found in the repository."
    
    formatted = "Current Cursor Rules in Repository:\n\n"
    for rule in rules:
        formatted += f"Rule: {rule.file_path}\n"
        formatted += f"```mdc\n{rule.content}\n```\n\n"
    
    return formatted 