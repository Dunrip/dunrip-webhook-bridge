import sys
from app.infra import circuit_breaker as _m

sys.modules[__name__] = _m
