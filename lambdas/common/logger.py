import logging
import sys

def get_logger(name: str = __name__, level: str = "INFO") -> logging.Logger:
    """Get a configured logger instance."""
    logger = logging.getLogger(name.split("/")[-1].replace(".py", ""))
    
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "[%(levelname)s] %(name)s.%(funcName)s:%(lineno)d - %(message)s"
        ))
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    return logger
