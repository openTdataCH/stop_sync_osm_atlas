import sys
import os

from backend.app import create_app
from backend.blueprints.data import _build_filtered_stop_query

app = create_app()

with app.app_context():
    args = {}
    query = _build_filtered_stop_query(46.0, 6.0, 47.0, 7.0, args)
    
    print("----- COMPILED QUERY -----")
    print(str(query.statement.compile(compile_kwargs={"literal_binds": True})))
