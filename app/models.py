from typing import List, Tuple, Optional
from pydantic import BaseModel
from .prompts import RuleGenerationOutput

class Suggestion(BaseModel):
    """A rule suggestion with its metadata"""
    id: int
    yaml_content: str
    is_accepted: bool = False
    
class SummaryState(BaseModel):
    """The current state of suggestions in a PR"""
    suggestions: List[Tuple[int, RuleGenerationOutput]]
    is_applied: bool = False
    
    def add_suggestion(self, suggestion_id: int, rule_output: RuleGenerationOutput) -> None:
        """Add a new accepted suggestion"""
        self.suggestions.append((suggestion_id, rule_output))
        
    def remove_suggestion(self, suggestion_id: int) -> None:
        """Remove a suggestion by ID"""
        self.suggestions = [(id, output) for id, output in self.suggestions if id != suggestion_id]
        
    def is_empty(self) -> bool:
        """Check if there are any suggestions"""
        return len(self.suggestions) == 0
        
    def copy(self) -> 'SummaryState':
        """Create a copy of the current state"""
        return SummaryState(
            suggestions=self.suggestions.copy(),
            is_applied=self.is_applied
        ) 