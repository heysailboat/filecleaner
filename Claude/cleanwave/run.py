#!/usr/bin/env python3
"""
CleanWave — run this to start the cleaner.
  python run.py              # scan Desktop, Documents, Downloads, Music, Movies, Pictures
  python run.py --home       # scan entire home directory
  python run.py --dir ~/Downloads
  python run.py --dry-run    # preview only, nothing moves
  python run.py --old-days 180  # override the 'old file' threshold
"""
from cleanwave.main import main

if __name__ == "__main__":
    main()
