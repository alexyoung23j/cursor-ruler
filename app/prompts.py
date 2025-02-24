from typing import List, Literal, Union, Optional
from pydantic import BaseModel, Field, model_validator

class RuleAnalysisOutput(BaseModel):
    """Output schema for the first stage LLM call that decides if a comment deserves a rule"""
    should_create_rule: bool = Field(description="Whether this comment deserves a cursor rule")
    reason: str = Field(description="Detailed explanation of why this comment does or doesn't deserve a rule. Should be no more than 1 sentence.")

class RuleChange(BaseModel):
    """Represents a change to a cursor rule file"""
    type: Literal["addition", "replacement"] = Field(description="The type of change to make")
    content: str = Field(description="The new content to add or the replacement content. Don't ever include the globs or description in the content field.")
    text_to_replace: Optional[str] = Field(description="For a replacement operation, the full text that should be fully replaced by the content field. Not needed for additions.", default=None)
    existing_content_context: Optional[str] = Field(description="Text that occurs IMMEDIATELY BEFORE the content to be added. Not needed for new files or replacements. Up to 2 Lines if possible.", default=None)
    is_new_file: bool = Field(description="Whether this change creates a new rule file", default=False)
    # For new files, these are required
    file_globs: Optional[List[str]] = Field(description="List of glob patterns for files this rule applies to (e.g. ['*.ts', '*.tsx']. Required when is_new_file is true. If you are making a change to this, return the new value, otherwise can leave blank.", default=None)
    file_description: Optional[str] = Field(description="The description of the cursor rules file. Required when is_new_file is true. If you are making a change to this, return the new value, otherwise can leave blank.", default=None)


    @model_validator(mode='after')
    def check_new_file_fields(self) -> 'RuleChange':
        """Validate that new files have required fields and existing file modifications don't"""
        if self.is_new_file:
            if not self.file_globs or not self.file_description:
                raise ValueError("New files must specify both file_globs and file_description")
            if self.existing_content_context or self.text_to_replace:
                raise ValueError("existing_content_context and text_to_replace should not be used with new files")
        
        if self.type == "replacement" and not self.text_to_replace:
            raise ValueError("text_to_replace is required for replacement operations")
        
        return self

class RuleGenerationOutput(BaseModel):
    """Output schema for the second stage LLM call that generates the rule YAML"""
    should_generate: bool = Field(description="Whether we should proceed with generating/updating a rule")
    reason: str = Field(description="Explanation of why we should or shouldn't generate/update a rule. At most one sentence.")
    operation: Optional[Literal["update", "create"]] = Field(description="The type of operation to perform on the rule file", default=None)
    file_path: Optional[str] = Field(description="The path to the rule file being modified, required for update operations. ALWAYS prefixed with .cursor/rules/", default=None)
    changes: List[RuleChange] = Field(description="List of changes to make to the rules")

    @model_validator(mode='after')
    def validate_operation_fields(self) -> 'RuleGenerationOutput':
        """Validate that operation and file_path are present when needed"""
        if self.should_generate and self.operation == "update" and not self.file_path:
            raise ValueError("file_path is required for update operations")
        return self

# First stage prompt: Analyze if a comment deserves a rule
ANALYSIS_PROMPT = """You are an expert at analyzing GitHub PR comments to determine if they warrant creating a Cursor rule.

Cursor rules are project-specific instructions that help control AI behavior in different parts of a codebase. 

IMPORTANT: A comment must meet ALL of these criteria to be considered:
1. Describes a CONCRETE pattern (not a proposed or currently discussed pattern)
2. Represents a CURRENT practice or Future Possibility. No temporary practices. 
3. Can be clearly applied across multiple files/contexts
4. Contains specific, actionable guidance

Examples of good rule candidates:
- "All React components should use functional style with hooks, not classes"
- "API response types should always be defined in types/api/responses/"
- "Use the ErrorBoundary component to handle all route-level errors"
- "Integration tests for API endpoints belong in tests/integration/api/"
- "use flexbox for layout, don't use grid"
- "use zod for API response validation"

Examples that should be REJECTED:
- Discussions or explorations ("We could try...", "What if we...", "Consider...")
- Architectural suggestions without consensus ("I think we should...")
- Questions or open-ended feedback ("How about...?")
- Vague principles without specific patterns ("Keep it modular")
- One-off fixes or implementation details
- Comments about code that won't be repeated elsewhere
- Obvious programming practices that don't need enforcement

Here is the PR comment to analyze:
{comment}

Additional context:
{context}

Based on the criteria above, could this comment potentially describe a pattern that should be turned into a Cursor rule? 
Remember: err on the side of rejection - it's better to miss a valid rule than to create unnecessary ones."""

# Second stage prompt: Generate the rule
GENERATION_PROMPT = """You are an expert at analyzing GitHub PR comments and creating Cursor rules.

Your task has two parts:
1. First, thoroughly analyze whether this comment should become a Cursor rule
2. If you decide yes, then specify the changes needed

A Cursor rule helps control AI behavior in different parts of a codebase by providing instructions about patterns, styles, and best practices.

IMPORTANT: Before considering rule generation, verify that the comment represents:
1. An ESTABLISHED pattern (not a proposal or discussion)
2. A CURRENT practice (not future possibilities)
3. Specific, actionable guidance
4. A pattern that will apply across multiple contexts and to multiple files

Comments that should be IMMEDIATELY REJECTED:
- Discussions or explorations ("We could try...", "What if we...")
- Questions or open-ended feedback
- Implementation details specific to one situation
- Valid comments that are already covered by existing rules

If you decide NOT to create a rule, your response should look like:
{{
    "should_generate": false,
    "reason": "Clear explanation of why this shouldn't become a rule",
    "operation": null,
    "file_path": null,
    "changes": []
}}

If you decide to make changes, your response should specify each change like this:
{{
    "should_generate": true,
    "reason": "Clear explanation of why this should become a rule",
    "operation": "update",
    "file_path": ".cursor/rules/performance-guidelines.mdc",
    "changes": [
        {{
            "type": "addition",
            "content": "<existing content right before the new content>",
            "existing_content_context": "up to 2 lines of text that occurs IMMEDIATELY BEFORE the content to be added",
            "is_new_file": false,
            "file_description": "Guidelines for the new pattern",
            "file_globs": ["*.ts", "*.tsx"],
        }}
    ]
}}

For creating new files:
{{
    "should_generate": true,
    "reason": "This pattern needs a new dedicated rule file",
    "operation": "create",
    "file_path": "name of new file, all lowercase, no spaces. ALWAYS prefixed with .cursor/rules/",
    "changes": [
        {{
            "type": "addition",
            "content": "Content of the new file, don't include the globs or description here.",
            "is_new_file": true,
            "file_description": "Guidelines for the new pattern",
            "file_globs": ["*.ts", "*.tsx"],
        }}
    ]
}}

Key points about changes:
1. For existing files:
   - Include context RIGHT BEFORE the content to be added or replaced to help locate where to make the change
   - For additions, the context is where the new content should be added after
   - For replacements, the context is the content that should be replaced
   - To modify glob or description fields, set the 'field' parameter and provide the old value as context
2. For new files:
   - Set is_new_file to true
   - Provide the pattern content
   - Provide file_description and file_globs (both required)
   - file_globs can be a list of patterns (e.g. ["*.ts", "*.tsx"])
   - Do not include context
3. Content should be properly formatted markdown
4. Keep changes focused and minimal - only include what's changing
5. Add new content after existing content. Try to always avoiding inserting in the middle unless super necessary.
6. ONLY ADD ONE CHANGE in the "changes" array. Combine all your changes (content, globs, and description) if they exist into just one.
7. All file paths should be prefixed with .cursor/rules/
8. Avoid leading \ns in the content field.

Key points about rules themselves:
1. Rules should be concise and to the point.
2. Rules should be written in markdown.
3. Rules should be written in a way that is easy to understand and apply.
4. Avoid giving examples in the rule file.
5. Generally be fairly sparing when assigning globs, only assign them when absolutely necessary.

Here is the PR comment to analyze:
{comment}

Code context:
{context}

Existing rules in the codebase:
{rules}
""" 