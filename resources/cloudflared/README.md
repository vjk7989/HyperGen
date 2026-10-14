# cloudflared build input

`scripts/prepare-cloudflared.mjs` downloads the pinned official Cloudflare
binary for the native build runner, verifies its SHA-256 digest, and places it
in this directory. Downloaded binaries are ignored by Git and bundled into the
corresponding HyperGen package.
