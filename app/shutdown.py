from app.startup import ApplicationComponents
from utils.logging import LogManager


class ShutdownManager:
    @staticmethod
    async def shutdown(components: ApplicationComponents) -> None:
        logger = LogManager.get_logger("shutdown")
        logger.info("Initiating shutdown")

        try:
            if hasattr(components, "websocket_manager"):
                await components.websocket_manager.disconnect()
                logger.info("WebSocket disconnected")
        except Exception as e:
            logger.error("WebSocket disconnect error: %s", e)

        try:
            if hasattr(components, "paper_broker"):
                await components.paper_broker.disconnect()
        except Exception as e:
            logger.error("Paper broker disconnect error: %s", e)

        try:
            if hasattr(components, "upstox_broker"):
                await components.upstox_broker.disconnect()
        except Exception as e:
            logger.error("Upstox broker disconnect error: %s", e)

        try:
            if hasattr(components, "db"):
                components.db.close()
                logger.info("Database connection closed")
        except Exception as e:
            logger.error("Database close error: %s", e)

        logger.info("Shutdown complete")
