from .main import app
from .ops import router as ops_router
from .performance import router as performance_router
from .engagement import router as engagement_router
from .commercial import router as commercial_router
from .communications import router as communications_router
from .branding import router as branding_router
from .lifecycle import router as lifecycle_router
from .growth import router as growth_router
from .corporate_api import router as corporate_api_router
from .tenancy import router as tenancy_router
from .competition import router as competition_router
from .tenant_billing import router as tenant_billing_router
from .realtime import router as realtime_router

# Keep the established core application intact while composing newer feature
# routers in one production entry point.
app.include_router(performance_router)
app.include_router(ops_router)
app.include_router(engagement_router)
app.include_router(commercial_router)
app.include_router(communications_router)
app.include_router(branding_router)
app.include_router(lifecycle_router)

app.include_router(growth_router)
app.include_router(corporate_api_router)

app.include_router(tenancy_router)
app.include_router(competition_router)
app.include_router(tenant_billing_router)

app.include_router(realtime_router)
