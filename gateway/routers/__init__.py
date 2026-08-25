"""Router aggregation — imports all routers for clean registration in main.py."""

from routers.tools import router as tools_router
from routers.verify import router as verify_router
from routers.servers import router as servers_router
from routers.settings import router as settings_router
from routers.unity import router as unity_router
from routers.blender import router as blender_router
from routers.effects import router as effects_router
from routers.abaqus import router as abaqus_router

routers = [tools_router, verify_router, servers_router, settings_router, unity_router, blender_router, effects_router, abaqus_router]
