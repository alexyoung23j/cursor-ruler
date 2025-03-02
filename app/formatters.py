from app.cursor_rules import CursorRule
from .constants import SUMMARY_SIGNATURE, SUGGESTION_SIGNATURE, APPLIED_SIGNATURE, APPLY_COMMAND
from .models import SummaryState
from .prompts import RuleGenerationOutput, RuleChange
from .rule_applier import merge_rule_changes
import json
from typing import List, Tuple
import logging
import difflib

logger = logging.getLogger(__name__)

def generate_diff(old_text: str, new_text: str) -> List[Tuple[str, str]]:
    """Generate a GitHub-style diff between old and new text.
    Returns a list of tuples (prefix, line) where prefix is:
    - '-' for removed lines
    - '+' for added lines
    - ' ' for context lines
    """
    old_lines = old_text.split('\n')
    new_lines = new_text.split('\n')
    
    differ = difflib.Differ()
    diff = list(differ.compare(old_lines, new_lines))
    
    # Convert differ output to GitHub style
    result = []
    for line in diff:
        if line.startswith('  '):  # Unchanged
            result.append((' ', line[2:]))
        elif line.startswith('- '):  # Removed
            result.append(('-', line[2:]))
        elif line.startswith('+ '):  # Added
            result.append(('+', line[2:]))
        # Skip '?' lines from differ output
    
    return result

def format_suggestion_comment(rule: RuleGenerationOutput, thread_root_id: int, current_rules: List[CursorRule]) -> str:
    """Format a comment with the rule suggestion and checkbox.
    Includes:
    1. A hidden marker to track which thread this suggestion belongs to
    2. The raw RuleGenerationOutput as hidden JSON for later processing
    3. A human-readable diff showing the changes based on current rules
    4. A checkbox for accepting the suggestion
    """
    # Start with the signature and thread marker
    comment = [
        SUGGESTION_SIGNATURE,
        f"<!--thread-root-{thread_root_id}-->",
        "",
        f"I suggest {'creating a new rules file called' if rule.operation == 'create' else 'updating'} `{rule.file_path}` as follows:",
        ""
    ]

    # Add the hidden RuleGenerationOutput as JSON
    comment.extend([
        "<!--rule-generation-output",
        json.dumps(rule.model_dump()),
        "-->",
        ""
    ])

    # Generate human-readable diff for each change
    for change in rule.changes:
        if change.is_new_file:
            print(f"New file: {change.content}")
            
            comment.extend([
                "",
                "**Description:**",
                "```",
                f"{change.file_description}",
                "```",
                "",
                "**Globs:**",
                "```",
                # Format globs as comma-separated quoted strings
                ", ".join(f'{g}' for g in (change.file_globs if isinstance(change.file_globs, list) else [change.file_globs])),
                "```",
                "Content:",
                "```diff",
                # Format each line of content with a '+' prefix
                *[f"+ {line}" for line in change.content.split('\n')],
                "```",
                ""
            ])
        else:
            # Find the existing rule content
            existing_rule = next((r for r in current_rules if r.file_path == rule.file_path), None)
            if not existing_rule:
                logger.warning(f"Could not find existing rule {rule.file_path} in current rules")
                continue

            if change.file_description and change.file_description != existing_rule.description:
                comment.extend([
                    "**Description:**",
                    "```diff",
                    f"- {existing_rule.description}",
                    f"+ {change.file_description}",
                    "```",
                    ""
                ])

             # For existing files, show the diff
            if change.file_globs and set(change.file_globs) != set(existing_rule.globs):
                old_globs = existing_rule.globs if isinstance(existing_rule.globs, list) else [existing_rule.globs]
                new_globs = change.file_globs if isinstance(change.file_globs, list) else [change.file_globs]
                
                old_globs_str = ", ".join(f'"{g}"' for g in old_globs)
                new_globs_str = ", ".join(f'"{g}"' for g in new_globs)
                
                comment.extend([
                    "**Globs:**",
                    "```diff",
                    f"- {old_globs_str}",
                    f"+ {new_globs_str}",
                    "```",
                    ""
                ])

            if change.content:
                comment.extend([
                    "**Content:**",
                    "```diff"
                ])
                
                # Handle replacements separately and early
                if change.type == "replacement" and change.text_to_replace:
                    # For replacements, we don't need context - we know exactly what to replace
                    diff_lines = generate_diff(change.text_to_replace, change.content)
                    for prefix, line in diff_lines:
                        if prefix == '-':
                            comment.append(f"-{line}")
                        elif prefix == '+':
                            comment.append(f"+{line}")
                        else:
                            comment.append(f" {line}")
                else:
                    # Handle context-based updates and additions
                    existing_content = existing_rule.content.split('\n')
                    if change.existing_content_context:
                        # Find where to insert/replace based on context
                        context_lines = change.existing_content_context.split('\n')
                        context_found = False
                        
                        for i in range(len(existing_content)):
                            if i + len(context_lines) <= len(existing_content):
                                # Check if this position matches the context
                                if all(existing_content[i+j].strip() == context_lines[j].strip() for j in range(len(context_lines))):
                                    context_found = True
                                    # Found the context, show a few lines before
                                    start_idx = max(0, i - 3)
                                    for line in existing_content[start_idx:i]:
                                        comment.append(f" {line}")
                                    # Show the context line(s)
                                    for line in existing_content[i:i + len(context_lines)]:
                                        comment.append(f" {line}")
                                    
                                    # Show what's being added
                                    for line in change.content.split('\n'):
                                        comment.append(f"+{line}")
                                    
                                    # Show a few lines after if there's more content
                                    end_idx = min(len(existing_content), i + len(context_lines) + 3)
                                    if i + len(context_lines) < len(existing_content):
                                        for line in existing_content[i + len(context_lines):end_idx]:
                                            comment.append(f" {line}")
                                    break
                        
                        if not context_found:
                            # If context wasn't found, show the content as an addition at the end
                            logger.warning(f"Could not find context '{change.existing_content_context}' in {rule.file_path}")
                            if existing_content:
                                for line in existing_content[-3:]:
                                    comment.append(f" {line}")
                            for line in change.content.split('\n'):
                                comment.append(f"+{line}")
                    else:
                        # No context, just append at the end
                        # Show last few lines of existing content
                        if existing_content:
                            for line in existing_content[-3:]:
                                comment.append(f" {line}")
                        # Show the new content
                        for line in change.content.split('\n'):
                            comment.append(f"+{line}")

                comment.extend([
                    "```",
                    ""
                ])

    # Add the checkbox
    comment.extend([
        "Check the box below to add this suggestion to the summary of suggested changes. **Clicking will NOT commit anything to the PR.**",
        "- [ ] Accept this suggestion?",
    ])

    return "\n".join(comment)

def format_summary_comment(state: SummaryState, current_rules: List[CursorRule]) -> str:
    """Format the summary comment based on current state.
    Shows a combined diff of all changes that would be applied.
    """
    summary = f"{SUMMARY_SIGNATURE}\n\n"
    
    if state.is_applied:
        summary += f"{APPLIED_SIGNATURE}\n"
        summary += "These rules have been applied to the codebase. This PR's suggestions are now locked.\n\n"
        summary += "Applied Changes:\n"
    else:
        summary += "Changes to be applied:\n"
    
    if not state.is_empty():
        # Group changes by file
        changes_by_file = {}
        for suggestion_id, rule_output in state.suggestions:
            file_path = rule_output.file_path
            if file_path not in changes_by_file:
                changes_by_file[file_path] = []
            changes_by_file[file_path].append(rule_output)
        
        # Process each file's changes
        for file_path, file_changes in changes_by_file.items():
            summary += f"\nFile: `{file_path}`"
            
            # Find existing rule if this is an update
            existing_rule = next((r for r in current_rules if r.file_path == file_path), None)
            current_content = existing_rule.content if existing_rule else None
            
            # Get the merged content
            final_content = merge_rule_changes(file_changes, current_content)
            
            # Format the diff
            if not existing_rule:
                # For new files, show everything as added
                summary += " (new file)\n```diff\n"
                for line in final_content.split('\n'):
                    summary += f"+ {line}\n"
                summary += "```\n"
            else:
                summary += "\n```diff\n"
                
                # Split both contents into frontmatter and body
                def split_mdc_file(content: str) -> Tuple[str, str]:
                    if content.startswith('---\n'):
                        parts = content.split('---\n', 2)
                        if len(parts) >= 3:
                            return parts[1], parts[2]
                    return '', content
                
                old_frontmatter, old_body = split_mdc_file(current_content)
                new_frontmatter, new_body = split_mdc_file(final_content)
            
                # Check if frontmatter changed
                frontmatter_changed = old_frontmatter != new_frontmatter
                
                # Generate diffs for both parts
                if frontmatter_changed:
                    # Show frontmatter diff
                    frontmatter_diff = list(difflib.unified_diff(
                        old_frontmatter.split('\n'),
                        new_frontmatter.split('\n'),
                        lineterm=''
                    ))
                    # Skip the first two lines (diff headers)
                    for line in frontmatter_diff[2:]:
                        if line.startswith('+'):
                            summary += line + '\n'
                        elif line.startswith('-'):
                            summary += line + '\n'
                        else:
                            summary += ' ' + line[1:] + '\n'
                
                # Generate body diff
                body_diff = list(difflib.unified_diff(
                    old_body.split('\n'),
                    new_body.split('\n'),
                    lineterm=''
                ))
                
                # If we have both frontmatter and body changes, add a skip indicator
                if frontmatter_changed and len(body_diff) > 2:
                    summary += " ...\n"
                
                # Show body diff if it exists
                if len(body_diff) > 2:  # More than just the headers
                    for line in body_diff[2:]:  # Skip the first two lines (diff headers)
                        if line.startswith('+'):
                            summary += line + '\n'
                        elif line.startswith('-'):
                            summary += line + '\n'
                        else:
                            summary += ' ' + line[1:] + '\n'
                
                summary += "```\n"
        
        if not state.is_applied:
            summary += "\n**To apply these changes:**\n"
            summary += "Add a new comment on this PR with the text `/apply-cursor-rules` and nothing else.\n"
            
        # Add the hidden state
        summary += "\n<!--rule-changes\n"
        summary += json.dumps({
            "suggestions": [
                {
                    "id": id,
                    "rule_generation_output": output.model_dump()
                }
                for id, output in state.suggestions
            ]
        })
        summary += "\n-->\n"
    else:
        summary += "No suggestions accepted yet.\n\n"
    
    if not state.is_applied:
        summary += "\nℹ️ Once rules are applied, no further rule suggestions will be added to this PR. Always double check the generated commit before merging."
    
    return summary