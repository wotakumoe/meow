# Meow

**Meow** is a simple utility to batch-download `.torrent` files from [Nyaa](https://nyaa.si/).  
> [!WARNING]
> This tool only downloads `.torrent` files. You will still need a torrent client (e.g., qBittorrent, Transmission) to use them.



## Requirements

- [Python](https://www.python.org/downloads/) 3.8 or higher

> [!tip]
> Remember to check the "Add Python to PATH" option during Python installation.

### Install dependencies using pip:

```bash
pip install requests beautifulsoup4
```

## Usage
```
python meow.py "nyaa.si url"
```