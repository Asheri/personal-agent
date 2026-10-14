# Vendored: asciinema-player 3.10.0

Copied from `asciinema-player@3.10.0` on npm, Apache-2.0, see `LICENSE`.

Vendored, not loaded from a CDN. The documentation build has to be hermetic,
and the CI link check (`lycheeverse/lychee-action`, offline mode) cannot
reach a CDN URL to verify it. A dead or moved asset would surface as a broken
player in a reader's browser and nowhere else.

Update by replacing both files from the same release and bumping the version
in this file:

```bash
VERSION=3.10.0
BASE="https://cdn.jsdelivr.net/npm/asciinema-player@${VERSION}/dist/bundle"
curl -sfL -o asciinema-player.min.js "${BASE}/asciinema-player.min.js"
curl -sfL -o asciinema-player.css "${BASE}/asciinema-player.css"
curl -sfL -o LICENSE "https://raw.githubusercontent.com/asciinema/asciinema-player/v${VERSION}/LICENSE"
```
