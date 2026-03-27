"""Line-by-line profiler package for Python.

This package provides a simple context manager interface for profiling code blocks
and functions with detailed line-by-line timing information.
"""

# 🟢 Import der Hauptklasse aus dem Modul

from lineprofiler.profiler import (
    FunctionStats,
    LineProfiler,
    LineStats,
)

# 🟢 Definiere was beim `from lineprofiler import *` importiert wird

__all__ = [
    "LineProfiler",
    "LineStats", 
    "FunctionStats",
]

# 🟢 Version des Pakets

__version__ = "1.0.0"
