## Permissions and Roles

This project has three effective roles: anonymous (not logged in), authenticated user, and admin.

### Anonymous (not logged in)
- Can access the web UI pages.
- Can save non‑persistent problem solutions via `/api/save_solution`.
- Can save non‑persistent notes:
  - `/api/save_note/atlas`, `/api/save_note/osm`
- Cannot make solutions or notes persistent in any way (UI should notify to log in).
- Can view lists:
  - `/api/persistent_data`
  - `/api/non_persistent_data`
- Cannot modify/revert/clean persistent data.

### Authenticated users
- Everything anonymous users can do, plus:
- Can make persistent individually (not in bulk):
  - `/api/make_solution_persistent`
  - `/api/make_note_persistent/<atlas|osm>`
- Can delete or make non‑persistent their own persistent records (they must be the author):
  - `DELETE /api/persistent_data/<id>`
  - `/api/make_non_persistent/<solution_id>`

### Admins
- Everything users can do, plus:
- Can delete a specific persistent record:
  - `DELETE /api/persistent_data/<id>`
- Can mark a specific solution as non‑persistent:
  - `/api/make_non_persistent/<solution_id>`
- Can clear all persistent data:
  - `/api/clear_all_persistent`
- Can clear all non‑persistent data:
  - `/api/clear_all_non-persistent`
- Can make persistent in bulk:
  - `/api/make_all_persistent`

Admin checks are enforced with an `is_admin` boolean on the user model and an admin guard in the backend.

### Becoming an admin (manage.py)
Use the management CLI to create users and grant admin rights. Inside the running container:

```bash
# List users
docker compose exec app python manage.py list-users

# Create a admin (add --admin to make it admin at creation time)
docker compose exec app python manage.py create-user --email you@example.com --password 'StrongPass' --admin

# Grant admin to an existing user
docker compose exec app python manage.py set-admin --email you@example.com --on

# Revoke admin
docker compose exec app python manage.py set-admin --email you@example.com --off
```

If you are running a different service name (e.g., `app-dev`), replace `app` accordingly.
