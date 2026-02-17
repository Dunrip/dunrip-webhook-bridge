import sys
from app import main as _m

sys.modules[__name__] = _m
