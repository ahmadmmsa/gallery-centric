from slugify import slugify as python_slugify

def generate_slug(text: str) -> str:
    return python_slugify(text)
