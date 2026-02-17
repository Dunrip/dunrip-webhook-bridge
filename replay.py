import sys
from app.api import replay as _m

sys.modules[__name__] = _m
