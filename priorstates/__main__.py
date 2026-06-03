"""Enable `python -m priorstates ...` as a PATH-independent entry point
(equivalent to the `priorstates` console script)."""
from .cli import main

if __name__ == "__main__":
    main()
