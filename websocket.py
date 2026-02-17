import sys
from app.api import websocket as _m

sys.modules[__name__] = _m
