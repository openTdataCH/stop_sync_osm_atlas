import os

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy


# Central SQLAlchemy extension instance shared by app and scheduler runtime code.
db = SQLAlchemy()

limiter = Limiter(
	key_func=get_remote_address,
	default_limits=["500 per minute"],
	storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
)

migrate = Migrate()
