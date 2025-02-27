import os
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv
import json
from unittest.mock import MagicMock, patch
import base64

# Load environment variables
load_dotenv()

# Add the app directory to the Python path
root_dir = Path(__file__).parent.parent
sys.path.append(str(root_dir))

import pytest
import yaml
from app.prompts import (
    RuleAnalysisOutput,
    RuleGenerationOutput,
    RuleChange,
    ANALYSIS_PROMPT,
    GENERATION_PROMPT
)
from app.llm import should_create_rule, generate_rule, get_llm, base_llm
from langchain.prompts import PromptTemplate
from app.cursor_rules import CursorRule
from app.models import SummaryState
from app.formatters import format_summary_comment
from app.rule_applier import apply_rule_changes

# Create prompt templates
analysis_template = PromptTemplate(
    template=ANALYSIS_PROMPT,
    input_variables=["comment", "context"]
)

generation_template = PromptTemplate(
    template=GENERATION_PROMPT,
    input_variables=["comment", "context", "rules"]
)

# Initialize LLM if not already initialized
if not base_llm:
    base_llm = get_llm()
    
    # Create analysis chain
    analysis_llm = base_llm.with_structured_output(RuleAnalysisOutput)
    analysis_chain = analysis_template | analysis_llm
    
    # Create generation chain
    generation_llm = base_llm.with_structured_output(RuleGenerationOutput)
    generation_chain = generation_template | generation_llm

def load_single_test_cases():
    """Load all individual test cases from the test_cases directory"""
    test_cases_dir = Path(__file__).parent / "test_cases"
    test_cases = []
    
    for i, case_file in enumerate(sorted(test_cases_dir.glob("*.yaml"))):
        with open(case_file) as f:
            data = yaml.safe_load(f)
            print(f"Loading test case {i}: {case_file} -> {data['name']}")
            test_cases.append(data)
    
    return test_cases

def load_merge_test_cases():
    """Load merge test cases from the merge_test_cases directory.
    Each subdirectory represents one merge test scenario."""
    test_cases_dir = Path(__file__).parent / "merge_test_cases"
    if not test_cases_dir.exists():
        return []
        
    test_cases = []
    
    for scenario_dir in sorted(test_cases_dir.iterdir()):
        if not scenario_dir.is_dir():
            continue
            
        # Load scenario metadata
        with open(scenario_dir / "metadata.yaml") as f:
            metadata = yaml.safe_load(f)
            
        # Load each suggestion in order
        suggestions = []
        for i, case_file in enumerate(sorted(scenario_dir.glob("[0-9]*.yaml")), 1):
            with open(case_file) as f:
                data = yaml.safe_load(f)
                suggestions.append(data)
                
        test_cases.append({
            "name": metadata["name"],
            "description": metadata.get("description", ""),
            "existing_rules": metadata.get("existing_rules", {}),
            "suggestions": suggestions
        })
        
    return test_cases

def print_separator(title: str):
    """Print a separator with a title"""
    print("\n" + "=" * 80)
    print(f" {title} ".center(80, "="))
    print("=" * 80 + "\n")

def convert_to_cursor_rules(rules_dict: dict) -> List[CursorRule]:
    """Convert a dictionary of rules to CursorRule objects"""
    current_rules = []
    for filename, content in rules_dict.items():
        # Split on first --- to get frontmatter
        parts = content.split('---', 2)
        if len(parts) >= 3:
            # Parse frontmatter
            try:
                frontmatter = yaml.safe_load(parts[1])
                description = frontmatter.get('description', '')
                globs = frontmatter.get('globs', '*')
                # Handle both string and list formats for globs
                if isinstance(globs, str):
                    # Split on commas and clean up whitespace
                    globs = [g.strip() for g in globs.split(',')]
            except yaml.YAMLError:
                print(f"Warning: Failed to parse frontmatter in {filename}, using defaults")
                globs = ['*']
                description = ''
        else:
            print(f"Warning: No frontmatter found in {filename}, using defaults")
            globs = ['*']
            description = ''
            
        current_rules.append(CursorRule(
            name=filename,
            description=description,
            globs=globs,
            content=content,
            file_path=filename
        ))
    return current_rules

def convert_to_rule_generation_output(expected_gen: dict) -> RuleGenerationOutput:
    """Convert expected generation dict to RuleGenerationOutput"""
    return RuleGenerationOutput(
        should_generate=expected_gen["should_generate"],
        reason=expected_gen["reason"],
        operation=expected_gen["operation"],
        file_path=expected_gen["file_path"],
        changes=[
            RuleChange(
                type=change["type"],
                content=change["content"],
                text_to_replace=change.get("text_to_replace"),
                existing_content_context=change.get("existing_content_context"),
                is_new_file=change.get("is_new_file", False),
                file_globs=change.get("file_globs"),
                file_description=change.get("file_description")
            )
            for change in expected_gen.get("changes", [])
        ]
    )

@pytest.mark.asyncio
@pytest.mark.parametrize("test_case", load_single_test_cases())
async def test_prompts(test_case):
    """Test both prompts against a test case"""
    print_separator(f"Testing case: {test_case['name']}")
    
    print("Input PR Comment:")
    print(test_case["pr_comment"])
    print("\nCode Context:")
    print(test_case.get("code_context", "None"))
    
    if test_case.get("existing_rules"):
        print("\nExisting Rules:")
        for filename, content in test_case["existing_rules"].items():
            print(f"\n{filename}:")
            print(content)
    
    test_passed = True
    
    # Run analysis stage
    if "expected_analysis" in test_case:
        print_separator("Analysis Stage")
        print("Expected Analysis:")
        print(json.dumps(test_case["expected_analysis"], indent=2))
        
        # Format existing rules for the prompt
        rules_context = ""
        for filename, content in test_case.get("existing_rules", {}).items():
            rules_context += f"File: {filename}\n```\n{content}\n```\n\n"
        
        result = await should_create_rule(
            test_case["pr_comment"],
            test_case.get("code_context")
        )
        print("\nActual Analysis:")
        print(json.dumps({
            "should_create_rule": result.should_create_rule,
            "reason": result.reason
        }, indent=2))
        
        # Check analysis result
        analysis_passed = result.should_create_rule == test_case["expected_analysis"]["should_create_rule"]
        test_passed = test_passed and analysis_passed
    
    # Run generation stage
    if "expected_generation" in test_case:
        print_separator("Generation Stage")
        print("Expected Generation:")
        print(json.dumps(test_case["expected_generation"], indent=2))
        
        # Format existing rules for the prompt
        rules_context = ""
        for filename, content in test_case.get("existing_rules", {}).items():
            rules_context += f"File: {filename}\n```\n{content}\n```\n\n"
        
        result = await generate_rule(
            test_case["pr_comment"],
            test_case.get("code_context"),
            rules_context
        )
        print("\nActual Generation:")
        print(json.dumps({
            "should_generate": result.should_generate,
            "reason": result.reason,
            "operation": result.operation,
            "file_path": result.file_path,
            "changes": [
                {
                    "type": c.type,
                    "content": c.content,
                    "text_to_replace": c.text_to_replace,
                    "existing_content_context": c.existing_content_context,
                    "is_new_file": c.is_new_file,
                    "file_globs": c.file_globs,
                    "file_description": c.file_description
                }
                for c in result.changes
            ] if result.should_generate else []
        }, indent=2))
        
        # Check generation results
        generation_passed = result.should_generate == test_case["expected_generation"]["should_generate"]
        if result.should_generate and test_case["expected_generation"]["should_generate"]:
            generation_passed = generation_passed and (
                result.operation == test_case["expected_generation"]["operation"] and
                # Only check file_path match for update operations
                (result.operation != "update" or 
                 result.file_path == test_case["expected_generation"]["file_path"])
            )
            
            # Compare changes
            if generation_passed and test_case["expected_generation"].get("changes"):
                expected_changes = test_case["expected_generation"]["changes"]
                actual_changes = result.changes
                
                # Check if we have the same number of changes
                if len(expected_changes) != len(actual_changes):
                    print(f"\nMismatch in number of changes: expected {len(expected_changes)}, got {len(actual_changes)}")
                    generation_passed = False
                else:
                    # Compare each change
                    for expected, actual in zip(expected_changes, actual_changes):
                        # For new files, verify required fields are present
                        if expected["is_new_file"] and actual.is_new_file:
                            if not actual.file_globs:
                                print("\nMissing file_globs for new file")
                                generation_passed = False
                                break
                            if not actual.file_description:
                                print("\nMissing file_description for new file")
                                generation_passed = False
                                break
                            
                        # For updates, check if the change maintains frontmatter
                        if expected["type"] == "replacement" and actual.type == "replacement":
                            if "---" in actual.text_to_replace and not actual.content.startswith('---\n'):
                                print("\nReplacement would remove frontmatter")
                                generation_passed = False
                                break
                
        test_passed = test_passed and generation_passed
    
    # Final assertion combining both stages
    assert test_passed, "Test failed - see above output for details"

@pytest.mark.parametrize("test_case", load_single_test_cases())
def test_format_suggestion_comment(test_case):
    """Test the format_suggestion_comment function using expected generation output from test cases"""
    if "expected_generation" not in test_case or not test_case["expected_generation"]["should_generate"]:
        pytest.skip("Test case doesn't have expected generation output or shouldn't generate")
    
    print_separator(f"Testing format_suggestion_comment for: {test_case['name']}")
    
    # Convert the expected generation to a RuleGenerationOutput
    rule = convert_to_rule_generation_output(test_case["expected_generation"])
    
    # Convert existing rules to proper CursorRule objects
    current_rules = convert_to_cursor_rules(test_case.get("existing_rules", {}))
    
    # Format the suggestion comment
    from app.formatters import format_suggestion_comment
    formatted_comment = format_suggestion_comment(rule, 123, current_rules)
    
    print("\nFormatted Suggestion Comment:")
    print(formatted_comment)
    
    # No assertions since we just want to see the output
    assert True

@pytest.mark.parametrize("test_case", load_merge_test_cases())
def test_merge_suggestions(test_case):
    """Test merging multiple suggestions into a summary comment"""
    print_separator(f"Testing merge scenario: {test_case['name']}")
    print(f"Description: {test_case['description']}")
    
    # Convert existing rules to CursorRule objects
    current_rules = convert_to_cursor_rules(test_case.get("existing_rules", {}))
    
    # Print existing rules
    if current_rules:
        print("\nExisting Rules:")
        for rule in current_rules:
            print(f"\n{rule.file_path}:")
            print(rule.content)
    
    # Create empty state
    state = SummaryState(suggestions=[])
    
    # Process each suggestion in order
    for i, suggestion in enumerate(test_case["suggestions"], 1):
        print(f"\nProcessing suggestion #{i}:")
        print(json.dumps(suggestion["expected_generation"], indent=2))
        
        # Convert to RuleGenerationOutput
        rule_output = convert_to_rule_generation_output(suggestion["expected_generation"])
        
        # Add to state
        state.add_suggestion(i, rule_output)
        
        # Generate summary
        summary = format_summary_comment(state, current_rules)
        
        print(f"\nSummary after suggestion #{i}:")
        print(summary)
    
    # No assertions, we just want to see the output
    assert True 

def load_specific_merge_test_case(case_name: str):
    """Load a specific merge test case by directory name"""
    test_cases_dir = Path(__file__).parent / "merge_test_cases"
    if not test_cases_dir.exists():
        return None
        
    case_dir = test_cases_dir / case_name
    if not case_dir.exists() or not case_dir.is_dir():
        return None
        
    # Load scenario metadata
    with open(case_dir / "metadata.yaml") as f:
        metadata = yaml.safe_load(f)
        
    # Load each suggestion in order
    suggestions = []
    for i, case_file in enumerate(sorted(case_dir.glob("[0-9]*.yaml")), 1):
        with open(case_file) as f:
            data = yaml.safe_load(f)
            suggestions.append(data)
            
    return {
        "name": metadata["name"],
        "description": metadata.get("description", ""),
        "existing_rules": metadata.get("existing_rules", {}),
        "suggestions": suggestions
    }

def get_available_merge_cases():
    """Get list of available merge test case directory names"""
    test_cases_dir = Path(__file__).parent / "merge_test_cases"
    if not test_cases_dir.exists():
        return []
    return [d.name for d in test_cases_dir.iterdir() if d.is_dir()]

@pytest.mark.parametrize(
    "case_name",
    get_available_merge_cases(),
    ids=lambda x: x  # Use the case name as the test ID
)
def test_merge_case(case_name: str):
    """Test a specific merge case directory"""
    test_case = load_specific_merge_test_case(case_name)
    if not test_case:
        print(f"Could not find merge test case: {case_name}")
        pytest.skip("Test case not found")
        return
        
    print_separator(f"Testing merge scenario: {test_case['name']}")
    print(f"Description: {test_case['description']}")
    
    # Convert existing rules to CursorRule objects
    current_rules = convert_to_cursor_rules(test_case.get("existing_rules", {}))
    
    # Print existing rules
    if current_rules:
        print("\nExisting Rules:")
        for rule in current_rules:
            print(f"\n{rule.file_path}:")
            print(rule.content)
    
    # Create empty state
    state = SummaryState(suggestions=[])
    
    # Process each suggestion in order
    for i, suggestion in enumerate(test_case["suggestions"], 1):
        print_separator(f"Processing suggestion #{i}")
        
        print("Suggestion Input:")
        print("\nPR Comment:")
        print(suggestion["pr_comment"])
        print("\nCode Context:")
        print(suggestion.get("code_context", "None"))
        
        print("\nExpected Generation:")
        print(json.dumps(suggestion["expected_generation"], indent=2))
        
        # Convert to RuleGenerationOutput
        rule_output = convert_to_rule_generation_output(suggestion["expected_generation"])
        
        # Add to state
        state.add_suggestion(i, rule_output)
        
        # Generate summary
        summary = format_summary_comment(state, current_rules)
        
        print_separator(f"Summary after suggestion #{i}")
        print(summary)
    
    # No assertions, we just want to see the output
    assert True 

def create_mock_pr():
    """Create a mock PR object with the minimum required attributes"""
    mock_pr = MagicMock()
    mock_repo = MagicMock()
    mock_pr.base.repo = mock_repo
    mock_pr.head.ref = "test-branch"
    return mock_pr

@pytest.mark.parametrize(
    "case_name",
    get_available_merge_cases(),
    ids=lambda x: x  # Use the case name as the test ID
)
def test_apply_changes(case_name: str):
    """Test applying multiple suggestions to files.
    This test mocks the GitHub API calls but validates the content we would commit."""
    test_case = load_specific_merge_test_case(case_name)
    if not test_case:
        print(f"Could not find merge test case: {case_name}")
        pytest.skip("Test case not found")
        return
        
    print_separator(f"Testing apply changes for: {test_case['name']}")
    print(f"Description: {test_case['description']}")
    
    # Convert existing rules to CursorRule objects
    current_rules = convert_to_cursor_rules(test_case.get("existing_rules", {}))
    
    # Print existing rules
    if current_rules:
        print("\nExisting Rules:")
        for rule in current_rules:
            print(f"\n{rule.file_path}:")
            print(rule.content)
    
    # Create empty state
    state = SummaryState(suggestions=[])
    
    # Process each suggestion in order
    for i, suggestion in enumerate(test_case["suggestions"], 1):
        print(f"\nProcessing suggestion #{i}:")
        print(json.dumps(suggestion["expected_generation"], indent=2))
        
        # Convert to RuleGenerationOutput
        rule_output = convert_to_rule_generation_output(suggestion["expected_generation"])
        
        # Add to state
        state.add_suggestion(i, rule_output)
    
    # Create a mock PR
    mock_pr = create_mock_pr()
    
    # Track what files would be created/updated
    expected_changes = {}
    
    # Mock the get_contents method to return existing files
    def mock_get_contents(path, ref):
        # Handle directory requests
        if path == '.cursor/rules':
            # Return an empty list if no rules exist, or a list of existing rules
            existing_rules = []
            for file_path in test_case.get("existing_rules", {}):
                if file_path.startswith('.cursor/rules/'):
                    mock_file = MagicMock()
                    mock_file.path = file_path
                    mock_file.type = "file"
                    existing_rules.append(mock_file)
            return existing_rules
            
        # Handle file requests
        if path in test_case.get("existing_rules", {}):
            content = test_case["existing_rules"][path]
            # Verify content has proper frontmatter
            if not content.startswith('---\n'):
                print(f"\nWarning: Mock file {path} missing frontmatter")
                # Add default frontmatter
                content = f"---\ndescription: Default description\nglobs: \"*\"\n---\n{content}"
            mock_file = MagicMock()
            mock_file.content = base64.b64encode(content.encode()).decode()
            mock_file.sha = "mock-sha"
            return mock_file
            
        # For new files, act as if they don't exist
        raise Exception(f"File not found: {path}")
    
    mock_pr.base.repo.get_contents = mock_get_contents
    
    # Mock the create_git_blob method
    def mock_create_git_blob(content, encoding):
        mock_blob = MagicMock()
        mock_blob.sha = "mock-blob-sha"
        # Verify content has proper frontmatter
        if content.startswith('---\n'):
            try:
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    frontmatter = yaml.safe_load(parts[1])
                    if not frontmatter.get('description'):
                        print("\nWarning: Content missing description in frontmatter")
                    if not frontmatter.get('globs'):
                        print("\nWarning: Content missing globs in frontmatter")
                else:
                    print("\nWarning: Content has invalid frontmatter format")
            except yaml.YAMLError:
                print("\nWarning: Failed to parse frontmatter in content")
        else:
            print("\nWarning: Content missing frontmatter")
        # Store the content that would be committed
        expected_changes[content] = True
        return mock_blob
    
    mock_pr.base.repo.create_git_blob = mock_create_git_blob
    
    # Mock other required methods
    mock_pr.base.repo.get_git_tree.return_value = MagicMock()
    mock_pr.base.repo.create_git_tree.return_value = MagicMock()
    mock_branch = MagicMock()
    mock_branch.commit = MagicMock()
    mock_pr.base.repo.get_branch.return_value = mock_branch
    mock_pr.base.repo.create_git_commit.return_value = MagicMock()
    mock_pr.base.repo.get_git_ref.return_value = MagicMock()
    
    # Apply the changes
    try:
        result = apply_rule_changes(mock_pr, state)
        print("\nChanges that would be committed:\n")
        for content in expected_changes.keys():
            print(content)
        print("\n")
    except Exception as e:
        print(f"\nError applying changes: {str(e)}")
        raise
    
    # No assertions yet - we just want to see what would be committed
    assert True 