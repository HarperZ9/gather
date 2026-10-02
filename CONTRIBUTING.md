# Contributing

This repository is part of the Project Telos public surface. Keep changes small, tested, and easy for public users and developers to verify.

Before sending a change:

- Read `README.md` and any local `AGENTS.md` instructions.
- Run the narrowest test or verification command that covers the change.
- Keep examples, package metadata, and public claims aligned with current behavior.
- Do not commit secrets, `.env` files, private corpus material, or generated caches.- After changing `src/gather/`, run `python scripts/build_client_package.py --sync-vendored` so the plugin folder carries the same server code.
