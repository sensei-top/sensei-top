"""Dump the API's OpenAPI schema to stdout, without starting a server.

The frontend's TypeScript types are generated from this (``pnpm gen:types``),
so schema generation has to work offline, in CI, and with no database present.
"""

import json
import sys

from sensei_top.api import create_app

if __name__ == "__main__":
    # The path is only recorded on app.state; generating the schema opens no
    # database and touches no endpoint.
    json.dump(create_app("unused.db").openapi(), sys.stdout, indent=2)
