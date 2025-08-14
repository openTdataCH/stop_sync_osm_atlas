from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_migrate import Migrate

# Central SQLAlchemy extension instance
db = SQLAlchemy()

# Auth/session extensions
login_manager = LoginManager()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=["500 per minute"])
talisman = Talisman()

# Database migrations
migrate = Migrate()


