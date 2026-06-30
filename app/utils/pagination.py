import math

class Pagination:
    def __init__(self, page: int, per_page: int, total_items: int):
        self.page = max(1, page)
        self.per_page = max(1, per_page)
        self.total_items = total_items
        self.total_pages = math.ceil(total_items / per_page) if per_page > 0 else 0
        self.has_next = self.page < self.total_pages
        self.has_prev = self.page > 1
        
        # Calculate range of pages to display in pagination control
        # E.g. showing 5 pages around the current page
        max_pages_to_show = 5
        half = max_pages_to_show // 2
        
        start = max(1, self.page - half)
        end = min(self.total_pages, start + max_pages_to_show - 1)
        
        if end - start + 1 < max_pages_to_show:
            start = max(1, end - max_pages_to_show + 1)
            
        self.page_range = list(range(start, end + 1))
