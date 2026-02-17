import sys
from app.api import github_app as _m

sys.modules[__name__] = _m
