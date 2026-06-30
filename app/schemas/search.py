from typing import List, Dict, Any, Optional
from pydantic import BaseModel

class SearchResult(BaseModel):
    hits: List[Dict[str, Any]]
    total_hits: int
    page: int
    total_pages: int
    processing_time_ms: int
    facets: Optional[Dict[str, Any]] = None
