"""Datetime utility functions for API responses."""


def format_datetime(dt):
    """Convert datetime object to ISO format string with UTC timezone.
    
    Args:
        dt: A datetime object, string, None, or any other value
        
    Returns:
        - For datetime objects: ISO format string with 'Z' suffix (e.g., '2026-04-16T18:10:00Z')
        - For None: returns None
        - For other types: returns the value as-is
    """
    if dt is None:
        return None
    if hasattr(dt, 'isoformat'):
        iso_str = dt.isoformat()
        # If the datetime doesn't have timezone info, append Z for UTC
        if '+' not in iso_str and 'Z' not in iso_str:
            iso_str += 'Z'
        return iso_str
    return dt
