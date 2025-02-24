from typing import List, Dict, Optional, Tuple
from github import Github, Repository, PullRequest, ContentFile, InputGitTreeElement
import base64
import logging
from .models import SummaryState
from .prompts import RuleGenerationOutput, RuleChange
from .cursor_rules import CursorRule, get_current_rules

logger = logging.getLogger(__name__)

def merge_rule_changes(
    file_changes: List[RuleGenerationOutput],
    current_content: Optional[str] = None
) -> str:
    """Merge multiple rule changes into a single file content.
    
    Args:
        file_changes: List of RuleGenerationOutput objects for the same file
        current_content: Current content of the file, if it exists
        
    Returns:
        The merged content as a string
    """
    # Check if this is a new file
    has_new_file_change = any(
        any(c.is_new_file for c in rule.changes)
        for rule in file_changes
    )
    
    if has_new_file_change:
        # Get all new file changes
        new_file_changes = [
            change for rule in file_changes
            for change in rule.changes 
            if change.is_new_file
        ]
        
        if new_file_changes:
            # Use the most recent change for metadata
            latest_change = new_file_changes[-1]
            
            # Start with the YAML frontmatter
            final_content = "---\n"
            final_content += f"description: {latest_change.file_description}\n"
            
            # Format globs as comma-separated quoted strings
            globs = latest_change.file_globs if isinstance(latest_change.file_globs, list) else [latest_change.file_globs]
            globs_str = ", ".join(f'"{g}"' for g in globs)
            final_content += f"globs: {globs_str}\n"
            final_content += "---\n\n"
            
            # Concatenate content from all changes
            for i, change in enumerate(new_file_changes):
                if i > 0:  # Add newline between changes
                    final_content += "\n"
                final_content += change.content
            
            # Ensure content ends with newline
            if not final_content.endswith('\n'):
                final_content += '\n'
                
            return final_content
    
    # Start with current content or empty string
    final_content = current_content if current_content is not None else ""
    
    # Extract current metadata if it exists
    current_description = None
    current_globs = None
    if final_content.startswith('---\n'):
        try:
            parts = final_content.split('---\n', 2)
            metadata = parts[1]
            for line in metadata.split('\n'):
                if line.startswith('description:'):
                    current_description = line[len('description:'):].strip()
                elif line.startswith('globs:'):
                    current_globs = line[len('globs:'):].strip()
        except:
            logger.warning("Failed to parse current metadata, will use defaults")
    
    # Track if we need to update metadata
    new_description = current_description
    new_globs = current_globs
    
    # Apply changes in reverse order so most recent takes precedence
    for rule in reversed(file_changes):
        for change in rule.changes:
            # Update metadata if provided
            if change.file_description:
                new_description = change.file_description
            if change.file_globs:
                globs = change.file_globs if isinstance(change.file_globs, list) else [change.file_globs]
                new_globs = ", ".join(f'"{g}"' for g in globs)
            
            # Handle content changes
            if change.type == "replacement" and change.text_to_replace:
                # For replacements, replace the exact text
                final_content = final_content.replace(change.text_to_replace, change.content)
            elif change.existing_content_context:
                # For context-based changes, find the context and add content
                context_pos = final_content.find(change.existing_content_context)
                if context_pos != -1:
                    # Add after the context
                    context_end = context_pos + len(change.existing_content_context)
                    final_content = (
                        final_content[:context_end] + 
                        "\n" + 
                        change.content + 
                        final_content[context_end:]
                    )
                else:
                    # If context not found, append to end
                    if final_content and not final_content.endswith('\n'):
                        final_content += '\n'
                    final_content += change.content
            elif change.content:  # Only append if there's actual content
                # No context, just append
                if final_content and not final_content.endswith('\n'):
                    final_content += '\n'
                final_content += change.content
    
    # If we have metadata changes, reconstruct the file with new metadata
    if (new_description != current_description or new_globs != current_globs) and (new_description or new_globs):
        # Extract the body content (everything after the second ---)
        body_content = final_content
        if final_content.startswith('---\n'):
            try:
                body_content = final_content.split('---\n', 2)[2]
            except:
                pass
        
        # Reconstruct with new metadata
        final_content = "---\n"
        if new_description:
            final_content += f"description: {new_description}\n"
        if new_globs:
            final_content += f"globs: {new_globs}\n"
        final_content += "---\n\n"
        final_content += body_content
    
    return final_content

def get_file_content(repo: Repository, path: str, ref: str) -> Tuple[Optional[str], Optional[str]]:
    """Get a file's content and SHA from the repo. Returns (content, sha) tuple."""
    try:
        file_info = repo.get_contents(path, ref=ref)
        if isinstance(file_info, list):
            logger.warning(f"File path {path} returned multiple contents, using first one")
            file_info = file_info[0]
        content = base64.b64decode(file_info.content).decode('utf-8')
        return content, file_info.sha
    except:
        return None, None

def create_commit_for_changes(
    repo: Repository,
    branch: str,
    file_changes: Dict[str, Tuple[str, Optional[str]]]
) -> Dict:
    """Create a single commit with all file changes.
    
    Args:
        repo: The repository to commit to
        branch: The branch to commit to
        file_changes: Dict mapping file paths to (content, sha) tuples
                     If sha is None, it's a new file
    """
    try:
        # Create the tree with all file changes
        base_tree = repo.get_git_tree(sha=branch)
        tree_elements = []
        
        for file_path, (content, _) in file_changes.items():
            # Create a blob for the file content
            blob = repo.create_git_blob(content=content, encoding='utf-8')
            
            # Add the file to the tree using InputGitTreeElement
            element = InputGitTreeElement(
                path=file_path,
                mode='100644',  # Regular file
                type='blob',
                sha=blob.sha
            )
            tree_elements.append(element)
        
        # Create a new tree with all changes
        new_tree = repo.create_git_tree(tree_elements, base_tree=base_tree)
        
        # Get the latest commit as a GitCommit object
        branch_ref = repo.get_branch(branch)
        parent_commit = repo.get_git_commit(branch_ref.commit.sha)
        
        # Create the commit
        commit = repo.create_git_commit(
            message="Apply cursor rules changes",
            tree=new_tree,
            parents=[parent_commit]  # Pass the actual GitCommit object
        )
        
        # Update the branch reference
        ref = repo.get_git_ref(f"heads/{branch}")
        ref.edit(sha=commit.sha)
        
        return {"sha": commit.sha}
        
    except Exception as e:
        logger.error(f"Failed to create commit: {str(e)}")
        raise

def apply_rule_changes(pr: PullRequest, state: SummaryState) -> Dict[str, str]:
    """Apply all rule changes to the PR's branch in a single commit
    
    Returns a dict with the commit SHA
    """
    repo = pr.base.repo
    branch = pr.head.ref
    
    # Get current rules for context
    current_rules = get_current_rules(repo, ref=branch)
    
    # Group changes by file
    changes_by_file = {}
    for suggestion_id, rule_output in state.suggestions:
        file_path = rule_output.file_path
        if file_path not in changes_by_file:
            changes_by_file[file_path] = []
        changes_by_file[file_path].append(rule_output)
    
    # Process each file's changes
    final_changes = {}  # Maps file paths to (content, sha) tuples
    
    for file_path, file_changes in changes_by_file.items():
        try:
            # Get current file content and SHA if it exists
            current_content, current_sha = get_file_content(repo, file_path, branch)
            
            # Merge all changes for this file
            final_content = merge_rule_changes(file_changes, current_content)
            
            # Store the final content and SHA
            final_changes[file_path] = (final_content, current_sha if current_content is not None else None)
                
        except Exception as e:
            logger.error(f"Failed to process changes for {file_path}: {str(e)}")
            raise
    
    # Create a single commit with all changes
    result = create_commit_for_changes(repo, branch, final_changes)
    return result 