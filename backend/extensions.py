import os

from flask_sqlalchemy import SQLAlchemy


# Central SQLAlchemy extension instance shared by app and scheduler runtime code.
db = SQLAlchemy()


class _MissingLimiter:
	def __init__(self, dependency_name: str):
		self._dependency_name = dependency_name

	def init_app(self, _app, *args, **kwargs):
		raise RuntimeError(
			f"Rate limiting requires '{self._dependency_name}'. "
			"Install web dependencies for the app image."
		)

	def limit(self, *_args, **_kwargs):
		# Keep decorators import-safe in non-web environments.
		def _decorator(func):
			return func
		return _decorator


class _MissingInitAppExtension:
	def __init__(self, dependency_name: str, feature_name: str):
		self._dependency_name = dependency_name
		self._feature_name = feature_name

	def init_app(self, _app, *args, **kwargs):
		raise RuntimeError(
			f"{self._feature_name} requires '{self._dependency_name}'. "
			"Install web dependencies for the app image."
		)


try:
	from flask_limiter import Limiter
	from flask_limiter.util import get_remote_address

	limiter = Limiter(
		key_func=get_remote_address,
		default_limits=["500 per minute"],
		storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
	)
except ModuleNotFoundError:
	limiter = _MissingLimiter("Flask-Limiter")

try:
	from flask_migrate import Migrate

	migrate = Migrate()
except ModuleNotFoundError:
	migrate = _MissingInitAppExtension("Flask-Migrate", "Database migrations")


