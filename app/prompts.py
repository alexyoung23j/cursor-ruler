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

# Modular prompt components
# These components can be reused across different prompts

RULE_CRITERIA = """
IMPORTANT: A comment must meet ALL of these criteria to be considered:
1. Describes a CONCRETE pattern (not a proposed or currently discussed pattern)
2. Represents a CURRENT practice or Future Possibility. No temporary practices. 
3. Can be clearly applied across multiple files/contexts
4. Contains specific, actionable guidance
"""

RULE_REJECTION_CRITERIA = """
Comments that should be IMMEDIATELY REJECTED:
- Discussions or explorations ("We could try...", "What if we...")
- Questions or open-ended feedback
- Implementation details specific to one situation
- Valid comments that are already covered by existing rules
- Vague principles without specific patterns ("Keep it modular")
- One-off fixes or implementation details
- Comments about code that won't be repeated elsewhere
- Obvious programming practices that don't need enforcement
- Temporary practices that are not going to be permanent parts of the codebase
"""

RULE_STRUCTURE_GUIDELINES = """
Sections in a rules file should follow this structure:
1. Start with a clear, concise heading (H1 level)
2. Provide a brief context (1-2 sentences max)
3. List specific requirements in bullet points
4. Keep the entire rule under 5 lines when possible
5. Focus on actionable instructions, not explanations
6. IMPORTANT: Prefer creating new rule files over adding to existing ones:
   - Each section should focus on a specific, self-contained concept
   - Keep sections small and focused (typically under 20 lines total)
   - Only combine closely related sections in the same file
7. CRITICAL: Be extremely concise and minimal - include ONLY what was explicitly stated in the comment
8. Keep your updates as minimal as possible. Always favor an addition over a replacement when possible. 
"""

RULE_NAMING_CONVENTIONS = """
Rule files should follow these naming conventions:
1. Use kebab-case (e.g., api-integration.mdc)
2. For new repos with no existing rules, create '001-core-standards.mdc' as the first file
3. For existing repos, use numeric prefixes to categorize:
   - 001-099: Core/foundational rules
   - 100-199: Integration/API rules
   - 200-299: Pattern/role-specific rules
   - 300-399: Testing/QA rules
4. Choose the most specific category that applies
5. IMPORTANT: Always use the lowest available number in the appropriate range:
   - If creating the first file in a category, use the first number (e.g., 100 for Integration)
   - If adding to an existing category, use the next sequential number (e.g., if 001 exists, use 002)
"""

FILE_ORGANIZATION_GUIDELINES = """
When organizing rules:
1. Prefer creating new rule files over updating existing ones
2. Each rule file should focus on a specific, self-contained concept
3. Only combine closely related patterns in the same file
4. If a new rule doesn't clearly belong with existing rules, create a new file
5. Keep rule files small and focused (typically under 20 lines total)
"""

SEQUENTIAL_NUMBERING_GUIDELINES = """
When numbering rule files:
1. Always use the lowest available number in the appropriate category range
2. For the first file in a category, use the first number (e.g., 001, 100, 200)
3. For additional files in a category, use the next sequential number:
   - If files 001 and 002 exist, use 003
   - If files 100 and 102 exist, use 101 (fill gaps when possible)
4. Analyze existing rule files to determine the next available number
5. Note that later rules always supersede earlier ones, when in conflict.
"""

GLOB_PATTERN_GUIDELINES = """
When specifying glob patterns:
1. For language-specific rules, use appropriate file extensions (e.g., *.ts, *.tsx)
2. For directory-specific rules, use path patterns (e.g., src/components/**/*.tsx)
3. Avoid overly broad patterns unless the rule truly applies everywhere
"""

FIRST_RULE_GUIDELINES = """
When creating the FIRST rule in a repository:
1. Name the file '001-core-standards.mdc'
2. Focus on foundational patterns that apply broadly
3. Keep the description concise but comprehensive
4. Use glob patterns that cover the primary codebase files
5. Structure the content to be clear and actionable
"""

GOOD_RULE_EXAMPLES = """
Examples of good rule candidates (short):
- "Use functional React components with hooks, not classes"
- "API types go in types/api/responses/"
- "Use zod for API validation"
- "Let's stick with camelCase for all variable names"
- "Hey team, can we please use the logger instead of console.log? Thanks!"
- "Don't forget to add alt tags to all images"

Examples of good rule candidates (longer):
- "We've decided to standardize on using the Repository pattern for all data access. Each domain entity should have its own repository class in the repositories/ directory that handles all database operations."

- "For accessibility compliance, all interactive elements need proper ARIA attributes and keyboard navigation support. Buttons should have aria-labels when they don't have text content, and custom components should implement proper keyboard handlers."

- "Hey folks, I noticed we're doing state management in a bunch of different ways. Let's standardize on Redux for global state and React Context for component-specific state that needs to be shared. This will make the codebase way easier to understand!"

- "I'm seeing a lot of different approaches to testing. Going forward, let's use Jest for unit tests and Cypress for E2E. Unit tests should focus on business logic, not implementation details. And please remember to mock external dependencies!"
"""

CONCISENESS_GUIDELINES = """
When writing rules, be extremely concise:
1. Include ONLY what was explicitly stated in the comment - do not infer, expand, or guess
2. Do not add extra requirements that weren't mentioned
3. Use the exact terminology from the original comment when possible
4. Aim for the shortest possible rule that captures the essential guidance
5. AVOID explanations, justifications, or background information unless explicitly mentioned
6. DO NOT try to guess the intent beyond what was clearly stated
7. When in doubt, leave it out - shorter is better
8. A good rule is often just a heading and 1-3 bullet points
9. Maintain a professional tone in the rule regardless of the original comment's tone
"""

# First stage prompt: Analyze if a comment deserves a rule
ANALYSIS_PROMPT = f"""You are an expert at analyzing GitHub PR comments to determine if they warrant creating a Cursor rule.

Cursor rules are project-specific instructions that help control AI behavior in different parts of a codebase. 

{RULE_CRITERIA}

{GOOD_RULE_EXAMPLES}

{RULE_REJECTION_CRITERIA}

Here is the PR comment to analyze:
{{comment}}

Additional context:
{{context}}

Based on the criteria above, could this comment potentially describe a pattern that should be turned into a Cursor rule? 
Remember: err on the side of rejection - it's better to miss a valid rule than to create unnecessary ones."""

# Second stage prompt: Generate the rule
GENERATION_PROMPT = f"""You are an expert at analyzing GitHub PR comments and creating Cursor rules.

Your task has two parts:
1. First, thoroughly analyze whether this comment should become a Cursor rule
2. If you decide yes, then specify the changes needed

A Cursor rule helps control AI behavior in different parts of a codebase by providing instructions about patterns, styles, and best practices.

{RULE_CRITERIA}

{GOOD_RULE_EXAMPLES}

{RULE_REJECTION_CRITERIA}

{CONCISENESS_GUIDELINES}

If you decide NOT to create a rule, your response should look like:
{{{{
    "should_generate": false,
    "reason": "Clear explanation of why this shouldn't become a rule",
    "operation": null,
    "file_path": null,
    "changes": []
}}}}

{RULE_NAMING_CONVENTIONS}

{RULE_STRUCTURE_GUIDELINES}

{FILE_ORGANIZATION_GUIDELINES}

{SEQUENTIAL_NUMBERING_GUIDELINES}

{GLOB_PATTERN_GUIDELINES}

If you decide to make changes, your response should specify each change like this:
{{{{
    "should_generate": true,
    "reason": "Clear explanation of why this should become a rule",
    "operation": "update",
    "file_path": ".cursor/rules/100-api-integration.mdc",
    "changes": [
        {{{{
            "type": "addition",
            "content": "## API Response Types\n\n- Define API response types in types/api/responses/",
            "existing_content_context": "up to 2 lines of text that occurs IMMEDIATELY BEFORE the content to be added",
            "is_new_file": false,
            "file_description": "Guidelines for API integration patterns",
            "file_globs": ["src/api/**/*.ts"],
        }}}}
    ]
}}}}

For creating new files:
{{{{
    "should_generate": true,
    "reason": "This pattern needs a new dedicated rule file",
    "operation": "create",
    "file_path": ".cursor/rules/200-component-patterns.mdc",
    "changes": [
        {{{{
            "type": "addition",
            "content": "## React Components\n\n- Use functional components with hooks, not classes",
            "is_new_file": true,
            "file_description": "Guidelines for component patterns",
            "file_globs": ["src/components/**/*.tsx"],
        }}}}
    ]
}}}}

Key points about changes:
1. For existing files:
   - Include context RIGHT BEFORE the content to be added or replaced to help locate where to make the change
   - For additions, the context is where the new content should be added after
   - For replacements, the context is the content that should be replaced
   - To modify glob or description fields, set the 'field' parameter and provide the old value as context
   - Be VERY cautious about replacing existing content. Only do so if the comment CLEARLY contradicts the existing rules.
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
8. Avoid leading \\ns in the content field.

{FIRST_RULE_GUIDELINES if "{{rules}}" == "" else ""}

Here is the PR comment to analyze:
{{comment}}

Code context:
{{context}}

Existing rules in the codebase:
{{rules}}
""" 