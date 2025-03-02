from typing import Dict, Optional, List, Tuple
from app.prompts import RuleGenerationOutput
from github import Github
import logging
import os
from fastapi import HTTPException

from app.server_state import RecentSuggestion, get_state_manager
from .constants import (
    SUMMARY_SIGNATURE, SUGGESTION_SIGNATURE, APPLIED_SIGNATURE,
    BOT_APP_NAME, APPLY_COMMAND
)
from .models import SummaryState, Suggestion
from .formatters import format_suggestion_comment, format_summary_comment
from .cursor_rules import CursorRule, get_current_rules, format_rules_for_llm
from .llm import should_create_rule, generate_rule
from github.Repository import Repository
from functools import lru_cache
import time
import base64
import json
from .rule_applier import apply_rule_changes
from datetime import datetime

logger = logging.getLogger(__name__)

# Cache for ETags
etag_cache = {}
comment_cache = {}

def log_rate_limit(github_client: Github):
    """Log current rate limit status"""
    try:
        core_rate_limit = github_client.get_rate_limit().core
        remaining = core_rate_limit.remaining
        total = core_rate_limit.limit
        reset_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(core_rate_limit.reset.timestamp()))
        logger.info(f"Rate limit: {remaining}/{total} remaining, resets at {reset_time}")
    except Exception as e:
        logger.error(f"Failed to get rate limit: {e}")

def is_bot_comment(comment: Dict) -> bool:
    """Check if the comment was made by our bot using user.type"""
    # Primary check: user type
    if comment.get("user", {}).get("type") == "Bot":
        return True
        
    # # Fallback: check bot username if type check fails
    # if comment.get("user", {}).get("login") == BOT_APP_NAME:
    #     return True
    
    return False

def is_suggestion_acceptance(comment: Dict) -> bool:
    """Check if this is someone accepting a suggestion by checking the box"""
    return (
        SUGGESTION_SIGNATURE in comment["body"]
        and "[x]" in comment["body"]
        and "Accept this suggestion?" in comment["body"]
        and is_bot_comment(comment)
    )

def is_apply_command(comment: Dict) -> bool:
    """Check if this comment is the apply command.
    The command must be the ONLY content of the comment, and it must not be in a summary comment."""
    # Skip if this is a summary comment
    if SUMMARY_SIGNATURE in comment["body"]:
        return False
        
    # Command must be the only content (allowing for whitespace)
    return comment["body"].strip() == APPLY_COMMAND

def extract_rule_generation_output(comment_body: str) -> str:
    """Extract RuleGenerationOutput JSON from a suggestion comment"""
    json_start = comment_body.find("<!--rule-generation-output") + len("<!--rule-generation-output")
    json_end = comment_body.find("-->", json_start)
    if json_start > len("<!--rule-generation-output") and json_end > json_start:
        return comment_body[json_start:json_end].strip()
    return ""

@lru_cache(maxsize=200)  # Increased cache size for multiple repos
def get_cached_comments(pr) -> Tuple[List, List]:
    """Cache PR comments to reduce API calls."""
    pr_key = f"{pr.base.repo.full_name}#{pr.number}"
    cached = comment_cache.get(pr_key)
    
    if cached:
        logger.debug(f"Using cached comments for PR {pr_key}")
        return cached
    
    # Fetch new comments
    issue_comments = list(pr.get_issue_comments())
    review_comments = list(pr.get_review_comments())
    result = (issue_comments, review_comments)
    
    # Cache the results with timestamp
    comment_cache[pr_key] = result
    return result

def invalidate_comment_cache(pr):
    """Invalidate comment cache for a specific PR"""
    pr_key = f"{pr.base.repo.full_name}#{pr.number}"
    if pr_key in comment_cache:
        logger.debug(f"Invalidating comment cache for PR {pr_key}")
        del comment_cache[pr_key]
    get_cached_comments.cache_clear()

def find_or_create_summary(pr, create_if_missing: bool = False, current_rules: List[CursorRule] = None) -> Optional[Dict]:
    """Find existing summary comment or create new one if requested"""
    # Always invalidate cache before looking for summary to ensure fresh data
    invalidate_comment_cache(pr)
    issue_comments, _ = get_cached_comments(pr)
    
    # More thorough check for existing summary
    for comment in issue_comments:
        try:
            if isinstance(comment.body, str) and SUMMARY_SIGNATURE in comment.body:
                logger.debug(f"Found existing summary comment #{comment.id}")
                return comment
        except AttributeError:
            logger.debug(f"Skipping comment that doesn't have a body attribute")
            continue
            
    if create_if_missing:
        logger.info("No existing summary found, creating new one")
        state = SummaryState(suggestions=[])
        summary = format_summary_comment(state, current_rules)
        new_comment = pr.create_issue_comment(summary)
        logger.debug(f"Created summary comment #{new_comment.id}")
        # Invalidate cache since we added a comment
        invalidate_comment_cache(pr)
        return new_comment
        
    logger.debug("No summary comment found and create_if_missing=False")
    return None

def parse_summary_state(summary_body: str) -> SummaryState:
    """Parse the current summary comment to get the state"""
    state = SummaryState(suggestions=[])
    
    if not summary_body or SUMMARY_SIGNATURE not in summary_body:
        return state
        
    # Set applied state
    was_applied = APPLIED_SIGNATURE in summary_body
    if was_applied:
        logger.warning(f"Found APPLIED_SIGNATURE in summary: {summary_body[:200]}...")
        
    state.is_applied = was_applied
    if state.is_applied:
        return state  # If it's applied, we're done - no need to parse suggestions
        
    # Extract hidden state
    json_start = summary_body.find("<!--rule-changes\n") + len("<!--rule-changes\n")
    json_end = summary_body.find("\n-->", json_start)
    
    if json_start > len("<!--rule-changes\n") and json_end > json_start:
        try:
            hidden_state = json.loads(summary_body[json_start:json_end])
            for suggestion in hidden_state["suggestions"]:
                state.add_suggestion(
                    suggestion["id"],
                    RuleGenerationOutput.model_validate(suggestion["rule_generation_output"])
                )
        except Exception as e:
            logger.error(f"Failed to parse hidden state: {e}")
            # Continue with empty state
            
    return state


async def get_code_context(pr, comment: Dict, event_type: str) -> Optional[str]:
    """Get the code context for a comment if it's a review comment.
    For review comments, fetches:
    1. The file path
    2. The specific line number
    3. The diff hunk (patch context)
    4. Additional lines before and after from the file
    """
    if event_type != "pull_request_review_comment":
        return None
        
    try:
        file_path = comment.get("path", "")
        line_num = comment.get("line", 0)
        diff_hunk = comment.get("diff_hunk", "")
        
        # Get the file content from the PR's head branch
        try:
            file_contents = pr.base.repo.get_contents(file_path, ref=pr.head.sha)
            if isinstance(file_contents, list):
                logger.warning(f"File path {file_path} returned multiple contents, using first one")
                file_contents = file_contents[0]
            
            file_content = base64.b64decode(file_contents.content).decode('utf-8')
            lines = file_content.split('\n')
            
            # Get 10 lines before and after, being careful of file boundaries
            start = max(0, line_num - 20)
            end = min(len(lines), line_num + 20)
            surrounding_code = '\n'.join(lines[start:end])
            
            context = f"File: {file_path}\n"
            context += f"Line: {line_num}\n\n"
            context += f"Diff hunk:\n```\n{diff_hunk}\n```\n\n"
            context += f"Broader file context:\n```\n{surrounding_code}\n```"
            return context
            
        except Exception as file_e:
            logger.warning(f"Could not get file content, falling back to diff only: {str(file_e)}")
            return f"File: {file_path}\nLine: {line_num}\n\n```\n{diff_hunk}\n```"
            
    except Exception as e:
        logger.error(f"Error getting code context: {str(e)}")
        return None

def get_root_comment_id(comment: Dict) -> int:
    """Get the ID of the root comment in a thread.
    If this comment is a reply, follow the chain up to find the original comment."""
    # For review comments, in_reply_to points to the root comment
    if "in_reply_to_id" in comment:
        return comment["in_reply_to_id"]
    # For issue comments, we need to check the parent
    if "parent" in comment and comment["parent"]:
        return comment["parent"]["id"]
    return comment["id"]

def has_existing_suggestion(pr, thread_root_id: int) -> bool:
    """Check if we've already made a suggestion for this comment thread"""
    try:
        marker = f"<!--thread-root-{thread_root_id}-->"
        logger.debug(f"Looking for marker for thread root #{thread_root_id}")
        
        # Use cached comments
        issue_comments, review_comments = get_cached_comments(pr)
        
        # Check all PR comments
        for comment in issue_comments:
            if SUGGESTION_SIGNATURE in comment.body and marker in comment.body:
                logger.debug(f"Found existing suggestion in issue comment #{comment.id} for thread root #{thread_root_id}")
                return True
                
        # Check review comments if needed
        for comment in review_comments:
            if SUGGESTION_SIGNATURE in comment.body and marker in comment.body:
                logger.debug(f"Found existing suggestion in review comment #{comment.id} for thread root #{thread_root_id}")
                return True
                
        logger.debug(f"No existing suggestion found for thread root #{thread_root_id}")
        return False
    except Exception as e:
        logger.error(f"Error checking for existing suggestions: {str(e)}")
        return False  # Fail safe - better to potentially duplicate than miss

@lru_cache(maxsize=200)  # Increased for multiple repos
def get_cached_rules(repo, ref: str) -> List[CursorRule]:
    """Cache cursor rules to reduce API calls."""
    cache_key = f"{repo.full_name}@{ref}"
    cached = comment_cache.get(cache_key)
    
    if cached:
        logger.debug(f"Using cached rules for {cache_key}")
        return cached
    
    # Fetch new rules
    rules = get_current_rules(repo, ref=ref)
    comment_cache[cache_key] = rules
    return rules

def clear_caches():
    """Clear all caches - useful if data gets stale"""
    get_cached_comments.cache_clear()
    get_cached_rules.cache_clear()
    comment_cache.clear()
    logger.info("All caches cleared")

def update_suggestion_status(state_manager, suggestion_id: str, status: str, comment_url: Optional[str] = None):
    """Update the status of an existing suggestion"""
    state = state_manager.get_state()
    for suggestion in state.recent_suggestions:
        if suggestion.id == suggestion_id:
            suggestion.status = status
            if comment_url:
                suggestion.comment_url = comment_url
            state_manager.save_state()
            logger.info(f"Updated suggestion {suggestion_id} status to {status}")
            return True
    return False

async def handle_suggestion_acceptance(
    pr,
    comment: Dict,
    summary_comment: Optional[Dict]
) -> Dict:
    """Handle when a user accepts a suggestion by checking the box"""
    logger.info(f"Processing suggestion acceptance in comment #{comment['id']}")
    
    # Extract RuleGenerationOutput from comment
    rule_output_json = extract_rule_generation_output(comment["body"])
    if not rule_output_json:
        logger.error("Could not find rule generation output in comment")
        raise HTTPException(status_code=400, detail="Invalid suggestion comment format")
        
    try:
        rule_output = RuleGenerationOutput.model_validate_json(rule_output_json)
    except Exception as e:
        logger.error(f"Failed to parse rule generation output: {e}")
        raise HTTPException(status_code=400, detail="Invalid rule generation output format")
    
    # Get current rules
    current_rules = get_cached_rules(pr.base.repo, pr.head.sha)
    
    # Get or create summary comment
    if not summary_comment:
        # Double check if summary exists (in case another process created it)
        summary_comment = find_or_create_summary(pr, create_if_missing=True, current_rules=current_rules)
        if not summary_comment:
            logger.error("Failed to find or create summary comment")
            raise HTTPException(status_code=500, detail="Failed to find or create summary comment")
    
    # Update summary state
    state = parse_summary_state(summary_comment.body)
    if state.is_applied:
        logger.error(f"Trying to accept suggestion but summary is already applied! Summary: {summary_comment.body[:200]}...")
        return {"message": "Rules already applied"}
    
    # Create a test state to check size
    test_state = state.copy()
    test_state.add_suggestion(comment["id"], rule_output)
    
    # Generate test summary and check size
    test_summary = format_summary_comment(test_state, current_rules)
    if len(test_summary.encode('utf-8')) > 60000:  # Leave ~5KB buffer for safety
        return {
            "message": "Cannot accept suggestion: Summary comment would exceed GitHub's size limit. Please apply current suggestions before adding more."
        }
    
    # If we get here, size is ok - proceed with real update
    state.add_suggestion(comment["id"], rule_output)
    
    # Update the comment
    summary = format_summary_comment(state, current_rules)
    summary_comment.edit(summary)
    
    # Find the original suggestion in our state to update its status
    state_manager = get_state_manager()
    state = state_manager.get_state()
    
    # Look for a suggestion with matching thread_root_id
    thread_root_id = get_root_comment_id(comment)
    found = False
    for suggestion in state.recent_suggestions:
        if suggestion.thread_root_id == thread_root_id:
            update_suggestion_status(state_manager, suggestion.id, "pending")
            found = True
            logger.info(f"Updated suggestion {suggestion.id} status to pending (thread root: {thread_root_id})")
            break
    
    if not found:
        logger.warning(f"Could not find original suggestion for thread root {thread_root_id}")
    
    return {"message": "Updated summary with accepted suggestion"}

async def handle_new_suggestion(
    pr,
    comment: Dict,
    event_type: str,
    dry_run: bool = False
) -> Dict:
    """Handle creating a new rule suggestion"""
    logger.debug(f"Handling potential new suggestion for comment #{comment.get('id')}")
    
    # First check if this is a bot comment or contains our signatures
    if any(sig in comment["body"] for sig in [SUMMARY_SIGNATURE, SUGGESTION_SIGNATURE, APPLIED_SIGNATURE]):
        logger.debug("Skipping suggestion for comment containing bot signatures")
        return {"message": "Skipping bot comment"}
    
    # Get the root comment ID for this thread
    thread_root_id = get_root_comment_id(comment)
    logger.debug(f"Identified thread root comment ID: {thread_root_id}")
    
    # Invalidate cache before checking for existing suggestions
    invalidate_comment_cache(pr)
    
    # Check if we've already made a suggestion for this thread
    if has_existing_suggestion(pr, thread_root_id):
        logger.info(f"Skipping duplicate suggestion for thread root #{thread_root_id}")
        return {"message": "Suggestion already exists for this thread"}
    
    # Get code context
    code_context = await get_code_context(pr, comment, event_type)
    
    # FIRST STAGE: Quick filter to see if this might be rule-worthy
    analysis = await should_create_rule(comment["body"], code_context)
    if not analysis.should_create_rule:
        logger.info(f"Initial filter rejected comment: {analysis.reason}")
        return {"message": "Comment does not need a rule suggestion"}
    
    # Get existing rules for context
    current_rules = get_cached_rules(pr.base.repo, pr.head.sha)
    rules_context = format_rules_for_llm(current_rules)

    # SECOND STAGE: Thorough analysis and potential rule generation
    logger.info("Comment passed initial filter, doing thorough analysis...")
    rule_generation = await generate_rule(comment["body"], code_context, rules_context)

    print(f"Rule generation: {rule_generation}")
    
    # Check if we should proceed with rule generation
    if not rule_generation.should_generate:
        logger.info(f"Thorough analysis rejected comment: {rule_generation.reason}")
        return {"message": "After analysis, determined comment does not need a rule suggestion"}
    
    # Format the suggestion
    logger.info(f"Generating rule suggestion for thread root #{thread_root_id}")
    suggestion_comment = format_suggestion_comment(rule_generation, thread_root_id, current_rules)
    
    # Get the state manager to track this suggestion
    state_manager = get_state_manager()
    
    if dry_run:
        # In dry run mode, just log what would have happened
        logger.info("DRY RUN MODE - Would have posted the suggestion")
        
        # Create a suggestion record for dry run
        suggestion = RecentSuggestion(
            id=str(comment["id"]),
            repository=pr.base.repo.full_name,
            pr_number=pr.number,
            file_path=rule_generation.file_path,
            timestamp=datetime.utcnow(),
            status="dry_run",
            suggestion_text=suggestion_comment,
            is_dry_run=True,
            dry_run_preview={
                "thread_root_id": thread_root_id,
                "content": suggestion_comment,
                "rule_generation": rule_generation.model_dump()
            }
        )
        state_manager.get_state().add_suggestion(suggestion)
        state_manager.save_state()
        
        return {
            "message": "Dry run - rule suggestion generated but not posted",
            "would_have_posted": True,
            "suggestion_preview": suggestion.dry_run_preview
        }
    
    # Actually post the suggestion if not in dry run mode
    try:
        new_comment = pr.create_review_comment_reply(
            comment["id"],
            suggestion_comment
        )
        
        # Create the suggestion record with thread_root_id for better tracking
        suggestion = RecentSuggestion(
            id=str(new_comment.id),
            repository=pr.base.repo.full_name,
            pr_number=pr.number,
            file_path=rule_generation.file_path,
            timestamp=datetime.utcnow(),
            status="suggested",  # Changed from "pending" to "suggested"
            suggestion_text=suggestion_comment,
            comment_url=new_comment.html_url,
            thread_root_id=thread_root_id
        )
        state_manager.get_state().add_suggestion(suggestion)
        state_manager.save_state()
        
        # Invalidate cache since we added a new comment
        invalidate_comment_cache(pr)
        
        logger.info(f"Posted suggestion #{new_comment.id} for thread root #{thread_root_id}")
        return {"message": "Posted new rule suggestion"}
    except Exception as e:
        logger.error(f"Failed to create suggestion comment: {str(e)}")
        raise

async def handle_apply_command(
    pr,
    comment: Dict
) -> Dict:
    """Handle when someone uses the apply command"""
    logger.info(f"Processing apply command from comment #{comment['id']}")
    
    # Find the summary comment
    summary_comment = find_or_create_summary(pr, create_if_missing=False)
    if not summary_comment:
        logger.warning("No summary comment found to apply")
        return {"message": "No suggestions to apply"}
        
    state = parse_summary_state(summary_comment.body)
    if state.is_empty():
        logger.warning("No accepted suggestions found to apply")
        return {"message": "No accepted suggestions to apply"}
        
    if state.is_applied:
        logger.error("Trying to apply but state is already applied!")
        return {"message": "Rules already applied"}
        
    # Apply the changes to the PR
    try:
        logger.info(f"Applying {len(state.suggestions)} suggestions")
        
        # Get state manager once for all updates
        state_manager = get_state_manager()
        
        try:
            # First attempt to apply the changes
            results = apply_rule_changes(pr, state)
            
            # If successful, mark as applied in summary
            logger.info("Setting state to applied via apply command")
            state.is_applied = True
            summary = format_summary_comment(state, get_cached_rules(pr.base.repo, pr.head.sha))
            summary_comment.edit(summary)
            
            # Update all suggestion statuses to applied
            success_count = 0
            for suggestion_tuple in state.suggestions:
                suggestion_id = str(suggestion_tuple[0])  # Extract just the ID from the tuple
                if update_suggestion_status(state_manager, suggestion_id, "applied"):
                    success_count += 1
                else:
                    logger.warning(f"Could not find suggestion {suggestion_id} to mark as applied")
            
            logger.info(f"Successfully marked {success_count}/{len(state.suggestions)} suggestions as applied")
            
            return {
                "message": f"Successfully applied {len(state.suggestions)} suggestions",
                "commits": results,
                "status_updates": success_count
            }
            
        except Exception as apply_error:
            # If applying changes fails, ensure we don't leave any suggestions in a bad state
            logger.error(f"Failed to apply changes, rolling back status updates: {str(apply_error)}")
            
            # Don't update any statuses since the apply failed
            raise apply_error
            
    except Exception as e:
        logger.error(f"Failed to apply changes: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def handle_pr_comment(
    github_client: Github,
    data: dict,
    dry_run: bool = False
) -> dict:
    """Handle a new PR comment"""
    try:
        repo_name = data["repository"]["full_name"]
        
        # Extract PR number based on event type
        if "pull_request" in data:
            pr_number = data["pull_request"]["number"]
        else:  # issue_comment
            if "pull_request" not in data["issue"]:
                logger.info("Ignoring issue comment not on a PR")
                return {"message": "Comment is not on a PR"}
            pr_number = data["issue"]["number"]
            
        event_type = "pull_request_review_comment" if "pull_request" in data else "issue_comment"
        comment = data["comment"]
        
        logger.info(f"Processing {event_type} comment on PR #{pr_number} in {repo_name}")
        log_rate_limit(github_client)  # Log rate limit at start
        
        repo = github_client.get_repo(repo_name)
        pr = repo.get_pull(pr_number)

        # Check for apply command first
        if is_apply_command(comment):
            if dry_run:
                logger.info("DRY RUN MODE - Would have processed apply command")
                return {
                    "message": "Dry run - apply command would have been processed",
                    "would_have_applied": True
                }
            logger.info("Processing apply command")
            return await handle_apply_command(pr, comment)
        
        # all issue comments besides the apply command are ignored
        if event_type == "issue_comment":
            logger.info(f"Ignoring unsupported event type: {event_type}")
            return {"message": "Issue comments are not processed"}
        
        # Find existing summary comment first
        summary_comment = find_or_create_summary(pr, create_if_missing=False)
        if summary_comment and APPLIED_SIGNATURE in summary_comment.body:
            logger.info("Ignoring comment as rules have already been applied")
            return {"message": "Rules already applied"}
        
        # Handle suggestion acceptance/unacceptance
        if is_suggestion_acceptance(comment):
            if dry_run:
                logger.info("DRY RUN MODE - Would have processed suggestion acceptance")
                return {
                    "message": "Dry run - suggestion acceptance would have been processed",
                    "would_have_accepted": True
                }
            return await handle_suggestion_acceptance(pr, comment, summary_comment)
        
        # For new suggestions, skip if this is a reply to another comment
        if "in_reply_to_id" in comment:
            logger.info("Skipping reply comment for suggestion processing")
            return {"message": "Reply comments are not processed for new suggestions"}
        
        # Handle new suggestion
        result = await handle_new_suggestion(pr, comment, event_type, dry_run)
        log_rate_limit(github_client)  # Log rate limit at end
        return result
        
    except Exception as e:
        import traceback
        logger.error(f"Error handling comment: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e)) 