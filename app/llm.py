from typing import Optional, List
from langchain_anthropic import ChatAnthropic
from langchain_community.chat_models import ChatOpenAI
from langchain.prompts import PromptTemplate
import os
import logging
from .prompts import (
    RuleAnalysisOutput,
    RuleGenerationOutput,
    RuleChange,
    ANALYSIS_PROMPT,
    GENERATION_PROMPT
)

logger = logging.getLogger(__name__)

# Configure logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Environment variables for API keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Define your prompt templates
analysis_template = PromptTemplate(
    template=ANALYSIS_PROMPT,
    input_variables=["comment", "context"]
)

generation_template = PromptTemplate(
    template=GENERATION_PROMPT,
    input_variables=["comment", "context", "rules"]
)

def get_llm():
    """Initialize and return the appropriate LLM based on available API keys"""
    if ANTHROPIC_API_KEY:
        logger.info("Using Anthropic Claude 3.5 Sonnet")
        return ChatAnthropic(
            model="claude-3-7-sonnet-20250219",
            anthropic_api_key=ANTHROPIC_API_KEY,
            temperature=0
        )
    elif OPENAI_API_KEY:
        logger.info("Using OpenAI GPT-4o")
        return ChatOpenAI(
            model="gpt-4o",
            openai_api_key=OPENAI_API_KEY,
            temperature=0
        )
    else:
        raise ValueError("No LLM API keys found. Please set either OPENAI_API_KEY or ANTHROPIC_API_KEY")

# Initialize the LLM and create chains
try:
    base_llm = get_llm()
    
    # Create analysis chain
    analysis_llm = base_llm.with_structured_output(RuleAnalysisOutput)
    analysis_chain = analysis_template | analysis_llm
    
    # Create generation chain
    generation_llm = base_llm.with_structured_output(RuleGenerationOutput)
    generation_chain = generation_template | generation_llm
    
except Exception as e:
    logger.error(f"Failed to initialize LLM: {str(e)}")
    analysis_chain = None
    generation_chain = None

async def should_create_rule(
    comment_body: str,
    code_context: Optional[str] = None
) -> RuleAnalysisOutput:
    """First stage LLM call: Quick analysis of whether a comment might deserve a cursor rule."""
    if not analysis_chain:
        logger.error("LLM not initialized")
        return RuleAnalysisOutput(
            should_create_rule=False,
            reason="LLM service not available"
        )
    
    logger.info(f"Analyzing comment: {comment_body}")
    context = f"Additional code context:\n{code_context}" if code_context else "No additional code context provided."
    
    try:
        return await analysis_chain.ainvoke({
            "comment": comment_body,
            "context": context
        })
    except Exception as e:
        logger.error(f"LLM analysis failed: {str(e)}")
        return RuleAnalysisOutput(
            should_create_rule=False,
            reason=f"Failed to analyze comment due to LLM service error: {str(e)}"
        )

async def generate_rule(
    comment_body: str,
    code_context: Optional[str],
    rules_context: str
) -> RuleGenerationOutput:
    """Second stage LLM call: Generate a cursor rule based on the comment."""
    if not generation_chain:
        raise RuntimeError("LLM service not available")
    
    logger.info(f"Generating rule for comment: {comment_body}")
    context = f"Code context:\n{code_context}" if code_context else "No code context provided."
    
    try:
        return await generation_chain.ainvoke({
            "comment": comment_body,
            "context": context,
            "rules": rules_context
        })
    except Exception as e:
        logger.error(f"LLM rule generation failed: {str(e)}")
        raise RuntimeError(f"Failed to generate rule due to LLM service error: {str(e)}")

def apply_rule_changes(current_content: str, changes: List[RuleChange]) -> str:
    """Apply a list of changes to the current rule content"""
    result = current_content
    
    for change in changes:
        if change.is_new_file:
            # For new files, just use the content as is
            if result:
                # If there's already content, this is an error
                raise ValueError(f"Multiple changes for new file {change.rule_file}")
            result = change.content
            continue
            
        # For existing files, validate context
        context_lines = change.context.strip().split('\n')
        if len(context_lines) != 2:
            raise ValueError(f"Context must be exactly 2 lines, got: {len(context_lines)}")
            
        if change.type == "addition":
            # Find where to add the new content
            context_pos = result.find(change.context)
            if context_pos == -1:
                # If context not found, append to end
                result += f"\n\n{change.content}"
            else:
                # Add after the context
                context_end = context_pos + len(change.context)
                result = result[:context_end] + f"\n{change.content}" + result[context_end:]
                
        elif change.type == "replacement":
            # Replace the context with the new content
            if change.field in ["glob", "description"]:
                # For glob and description fields, format as YAML field
                result = result.replace(change.context, f"{change.field}: {change.content}")
            else:
                result = result.replace(change.context, change.content)
    
    return result

def format_rule_yaml(rule: RuleGenerationOutput) -> dict:
    """Format changes into a dictionary mapping rule files to their new content"""
    # Group changes by rule file
    changes_by_file = {}
    for change in rule.changes:
        if change.rule_file not in changes_by_file:
            changes_by_file[change.rule_file] = []
        changes_by_file[change.rule_file].append(change)
    
    # For each file, apply its changes in sequence
    results = {}
    for file_path, file_changes in changes_by_file.items():
        # Check if this is a new file
        new_file_changes = [c for c in file_changes if c.is_new_file]
        is_new_file = bool(new_file_changes)
        
        if is_new_file:
            if len(new_file_changes) > 1:
                raise ValueError(f"Multiple new file changes for {file_path}")
            
            change = new_file_changes[0]
            # Format new file with YAML frontmatter
            yaml_content = ["---"]
            yaml_content.append("pattern: |")
            # Indent the content
            for line in change.content.split("\n"):
                yaml_content.append(f"  {line}")
            yaml_content.append(f"description: {change.file_description}")
            # Format globs as YAML list
            if len(change.file_globs) == 1:
                yaml_content.append(f"glob: {change.file_globs[0]}")
            else:
                yaml_content.append("glob:")
                for glob in change.file_globs:
                    yaml_content.append(f"  - {glob}")
            results[file_path] = "\n".join(yaml_content)
        else:
            # For existing files, we'd need to load the current content
            current_content = ""  # TODO: Load existing file content
            
            # Apply all changes for this file
            new_content = apply_rule_changes(current_content, file_changes)
            results[file_path] = new_content
    
    return results 