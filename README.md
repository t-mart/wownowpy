# wownowpy (python)

Python port of [wownow](https://github.com/t-mart/wownow) because that's now broken (hostname no longer resolves).

Here in Python, we use the [HTTP endpoints](https://wowdev.wiki/TACT#HTTP_URLs) instead of TCP sockets.

## Usage

```bash
uv tool install git+https://github.com/t-mart/wownowpy
uv run wownow --help
```

