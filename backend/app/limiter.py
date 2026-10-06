"""
Shared rate-limiter instance.

Import from here in every router that needs @limiter.limit():

    from app.limiter import limiter
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
