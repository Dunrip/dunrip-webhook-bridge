import sys
from app.models import models as _m

sys.modules[__name__] = _m
