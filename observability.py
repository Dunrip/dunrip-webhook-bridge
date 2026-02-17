import sys
from app.observability import observability as _m

sys.modules[__name__] = _m
