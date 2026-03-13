from flask_sqlalchemy import SQLAlchemy

import os

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_migrate import Migrate

# Central SQLAlchemy extension instance
db = SQLAlchemy()

limiter = Limiter(
	key_func=get_remote_address,
	default_limits=["500 per minute"],
	storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
)
talisman = Talisman()

# Database migrations
migrate = Migrate()


