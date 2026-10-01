from .main import app
from .ops import router as ops_router
from .performance import router as performance_router

# Keep the established core application intact while composing newer feature
# routers in one production entry point.
app.include_router(performance_router)
app.include_router(ops_router)
