"""Context-manager based line-by-line profiler for Python functions.

This module provides a simple context manager interface for profiling code blocks
and functions with detailed line-by-line timing information.

Test components:
- Context manager protocol (__enter__/__exit__)
- Accurate timing measurements with sys.settrace
- Proper trace function cleanup and restoration
- Thread-safe profiler state management
- Correct line timing calculations
"""
import inspect
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType, TracebackType

from typing_extensions import Self


@dataclass
class LineStats:
    """Statistics for a single line of code.

    Test components:
    - Correct accumulation of hits and total_time
    - Accurate average_time calculation
    - Proper handling of zero hits
    """

    line_number: int
    hits: int = 0
    total_time: float = 0.0

    @property
    def average_time(self) -> float:
        """Calculate average time per execution.

        Returns
        -------
            Average time in seconds, or 0.0 if no hits

        Test components:
        - Division by zero handling
        - Accurate time averaging
        """
        return self.total_time / self.hits if self.hits > 0 else 0.0


@dataclass
class FunctionStats:
    """Statistics for an entire function.

    Test components:
    - Correct line_stats dictionary management
    - Accurate source code storage
    - Proper total_time accumulation
    """

    filename: str
    function_name: str
    first_line: int
    line_stats: dict[int, LineStats] = field(default_factory=dict)
    source_lines: dict[int, str] = field(default_factory=dict)
    total_time: float = 0.0


class LineProfiler:
    """Context manager for line-by-line profiling of code blocks.

    Usage:
        profiler = LineProfiler()
        with profiler:
            # Code to profile
            result = some_function()

        profiler.print_stats()

    Test components:
    - Context manager __enter__ and __exit__ implementation
    - Correct trace function registration and cleanup
    - Accurate timing of line executions
    - Proper handling of nested function calls
    - Thread-safe state management
    - File and line number tracking
    """

    def __init__(self, project_folder: str | Path | None = None) -> None:
        """Initialize the profiler.

        Args:
            project_folder: Optional folder path to filter results (e.g., "pandapower_env")

        Test components:
        - Proper initialization of all tracking dictionaries
        - Correct default state setup
        - Path resolution for project_folder
        """
        self._function_stats: dict[tuple[str, str, int], FunctionStats] = {}
        self._enabled: bool = False
        self._last_time: float = 0.0
        self._last_line: int | None = None
        self._current_function_key: tuple[str, str, int] | None = None
        self._old_trace = sys.gettrace()

        # Store project folder for filtering
        if project_folder is not None:
            self._project_folder = Path(project_folder).resolve()
        else:
            # Auto-detect vom Caller

            caller_frame = inspect.currentframe()
            if caller_frame and caller_frame.f_back:
                caller_file = caller_frame.f_back.f_code.co_filename
                self._project_folder = self._find_repo_root(caller_file)

    def __enter__(self) -> Self:
        """Enable profiling when entering context.

        Returns
        -------
            Self for context manager protocol

        Test components:
        - Correct storage of previous trace function
        - Proper settrace registration
        - Accurate initial timestamp
        - State flag updates
        """
        self._enabled = True
        self._old_trace = sys.gettrace()
        sys.settrace(self._trace_callback)
        self._last_time = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Disable profiling when exiting context.

        Args:
            exc_type: Exception type if raised
            exc_val: Exception value if raised
            exc_tb: Exception traceback if raised

        Test components:
        - Proper trace function restoration
        - State cleanup on exit
        - Correct handling of exceptions during profiling
        - No interference with exception propagation
        """
        self._enabled = False
        sys.settrace(self._old_trace)

    def _trace_callback(  # noqa: ANN202, C901
        self,
        frame: FrameType,
        event: str,
        arg,  # noqa: ANN001, ARG002; needed for compliance
    ):
        """Trace function called by Python interpreter for each line.

        Args:
            frame: Current execution frame
            event: Event type ('call', 'line', 'return', etc.)
            arg: Event-specific argument

        Returns
        -------
            Self to continue tracing, or None to stop

        Test components:
        - Correct event type handling ('call', 'line', 'return')
        - Accurate time delta calculations
        - Proper frame inspection (filename, function name, line number)
        - FunctionStats creation and updates
        - Source code extraction and caching
        """
        if not self._enabled:
            return None

        current_time = time.perf_counter()

        if event == "call":
            # New function called
            filename = frame.f_code.co_filename
            if not self._is_in_project_folder(filename):
                return None
            function_name = frame.f_code.co_name
            first_line = frame.f_code.co_firstlineno

            key = (filename, function_name, first_line)

            if key not in self._function_stats:
                self._function_stats[key] = FunctionStats(
                    filename=filename,
                    function_name=function_name,
                    first_line=first_line,
                )
                # Load source lines
                self._load_source_lines(key)

            self._current_function_key = key
            self._last_time = current_time
            self._last_line = None

        elif event == "line":
            # Line executed
            if self._current_function_key is not None and self._last_line is not None:
                time_delta = current_time - self._last_time

                func_stats = self._function_stats[self._current_function_key]

                if self._last_line not in func_stats.line_stats:
                    func_stats.line_stats[self._last_line] = LineStats(
                        line_number=self._last_line,
                    )

                line_stats = func_stats.line_stats[self._last_line]
                line_stats.hits += 1
                line_stats.total_time += time_delta
                func_stats.total_time += time_delta

            self._last_line = frame.f_lineno
            self._last_time = current_time

        elif event == "return":
            # Function returning
            if self._current_function_key is not None and self._last_line is not None:
                time_delta = current_time - self._last_time

                func_stats = self._function_stats[self._current_function_key]

                if self._last_line not in func_stats.line_stats:
                    func_stats.line_stats[self._last_line] = LineStats(
                        line_number=self._last_line,
                    )

                line_stats = func_stats.line_stats[self._last_line]
                line_stats.hits += 1
                line_stats.total_time += time_delta
                func_stats.total_time += time_delta

            self._current_function_key = None
            self._last_line = None

        return self._trace_callback

    def _load_source_lines(self, key: tuple[str, str, int]) -> None:
        """Load source code lines for a function.

        Args:
            key: Tuple of (filename, function_name, first_line)

        Test components:
        - Correct file reading and line extraction
        - Proper handling of missing files
        - UTF-8 encoding support
        - Line number indexing
        """
        filename, _, _ = key
        func_stats = self._function_stats[key]

        try:
            path = Path(filename)
            if path.exists():
                with Path.open(path, encoding="utf-8") as f:
                    lines = f.readlines()
                    for i, line in enumerate(lines, start=1):
                        func_stats.source_lines[i] = line.rstrip()
        except (OSError, UnicodeDecodeError):
            # If we can't read the file, just continue
            pass

    def _find_repo_root(self, start_path: str) -> Path:
        """Return the git repo root (directory containing .git)."""
        p = Path(start_path).resolve()

        for parent in [p] + list(p.parents):  # noqa: RUF005
            if (parent / ".git").exists():
                return parent

        # No git repo found → fallback to start_path
        return p

    def _is_in_project_folder(self, filename: str) -> bool:
        if self._project_folder is None:
            return True # type: ignore[unreachable]

        try:
            file_path = Path(filename).resolve()
            # Prüfe ob file_path relativ zu project_folder ist
            try:
                file_path.relative_to(self._project_folder)
            except ValueError:
                return False
            else:
                return True
        except (OSError, ValueError):
            return False


    def print_stats(  # noqa: C901
        self,
        min_time_us: float = 0.0,
        top_n_lines: int | None = None,
        sort_by: str = "time",
    ) -> None:
        """Print detailed profiling statistics per function.

        Args:
            min_time_us: Minimum time in microseconds to display a line
            top_n_lines: If set, only show the top N lines per function
            sort_by: How to sort lines - "time" (total time), "hits" (call count),
                    or "line" (line number). Default is "time".

        Test components:
        - Correct formatting of time values (seconds to microseconds)
        - Proper sorting by line number, time, or hits
        - Accurate percentage calculations
        - Column alignment and formatting
        - Filtering based on min_time_us threshold
        - Correct limiting to top_n_lines
        - Project folder filtering
        """
        if not self._function_stats:
            print("No profiling data collected.")# noqa: T201
            return

        for key, func_stats in sorted(self._function_stats.items()):
            filename, function_name, first_line = key

            # Filter by project folder if set
            if not self._is_in_project_folder(filename):
                print(f"filename not in folde: {filename}")# noqa: T201
                continue

            if not func_stats.line_stats:
                continue

            print("=" * 100)# noqa: T201
            print(f"File: {filename}")# noqa: T201
            print(f"Function: {function_name} at line {first_line}")# noqa: T201
            print(f"Total time: {func_stats.total_time * 1e6:.1f} µs")# noqa: T201
            print("=" * 100)  # noqa: T201
            print(f"{'Line #':<8} {'Hits':<10} {'Time (µs)':<15} {'Per Hit (µs)':<15} {'% Time':<10} {'Line Content'}")  # noqa: T201
            print("-" * 100)  # noqa: T201

            # Collect all lines with stats
            line_data: list[tuple[int, LineStats]] = []
            for line_num in func_stats.line_stats:
                line_stats = func_stats.line_stats[line_num]
                time_us = line_stats.total_time * 1e6

                if time_us >= min_time_us:
                    line_data.append((line_num, line_stats))

            # Sort based on sort_by parameter
            if sort_by == "time":
                line_data.sort(key=lambda x: x[1].total_time, reverse=True)
            elif sort_by == "hits":
                line_data.sort(key=lambda x: x[1].hits, reverse=True)
            else:  # sort_by == "line"
                line_data.sort(key=lambda x: x[0])

            # Limit to top N if requested
            if top_n_lines is not None:
                line_data = line_data[:top_n_lines]

            # Print the lines
            for line_num, line_stats in line_data:
                time_us = line_stats.total_time * 1e6
                avg_time_us = line_stats.average_time * 1e6
                percent = (line_stats.total_time / func_stats.total_time * 100
                          if func_stats.total_time > 0 else 0.0)

                source_line = func_stats.source_lines.get(line_num, "")
                # Truncate long lines
                if len(source_line) > 50:  # noqa: PLR2004
                    source_line = source_line[:47] + "..."

                print(f"{line_num:<8} {line_stats.hits:<10} {time_us:<15.1f} "  # noqa: T201
                      f"{avg_time_us:<15.1f} {percent:<10.1f} {source_line}")

            print()  # noqa: T201

    def print_global_top_stats(  # noqa: C901, PLR0912
        self,
        top_n: int = 10,
        min_time_us: float = 0.0,
        sort_by: str = "time",
    ) -> None:
        """Print a global summary of the top lines across all functions.

        Args:
            top_n: Number of top lines to display
            min_time_us: Minimum time in microseconds to include a line
            sort_by: How to sort - "time" (total time) or "hits" (call count)

        Test components:
        - Correct aggregation across all functions
        - Proper sorting by time or hits
        - Project folder filtering
        - Accurate time and percentage calculations
        - Proper table formatting
        """
        all_lines: list[dict] = []

        for key, func_stats in self._function_stats.items():
            filename, function_name, first_line = key

            # Filter by project folder if set
            if not self._is_in_project_folder(filename):
                continue

            if not func_stats.line_stats:
                continue

            # Use relative path if possible, otherwise basename
            if self._project_folder is not None:
                try:
                    display_path = Path(filename).resolve().relative_to(self._project_folder)
                    short_filename = str(display_path)
                except (ValueError, OSError):
                    short_filename = Path(filename).name
            else:
                short_filename = Path(filename).name # type: ignore[unreachable]

            for line_num, line_stats in func_stats.line_stats.items():
                time_us = line_stats.total_time * 1e6

                if time_us < min_time_us:
                    continue

                all_lines.append({
                    "file": short_filename,
                    "function": function_name,
                    "line_num": line_num,
                    "hits": line_stats.hits,
                    "time_us": time_us,
                    "avg_time_us": line_stats.average_time * 1e6,
                    "percent": (line_stats.total_time / func_stats.total_time * 100
                               if func_stats.total_time > 0 else 0.0),
                    "source_line": func_stats.source_lines.get(line_num, ""),
                })

        if not all_lines:
            print("No profiling data above the threshold.")  # noqa: T201
            return

        # Sort by descending total time or hits
        if sort_by == "hits":
            all_lines.sort(key=lambda x: x["hits"], reverse=True)
        else:  # sort_by == "time"
            all_lines.sort(key=lambda x: x["time_us"], reverse=True)

        # Print header
        print("=" * 130)  # noqa: T201
        print(f"Top {top_n} lines across all functions (sorted by {sort_by})")  # noqa: T201
        print("=" * 130)  # noqa: T201
        print(f"{'File::Function':<50} {'Line':<6} {'Hits':<10} {'Time (µs)':<13} "  # noqa: T201
              f"{'Per Hit (µs)':<14} {'% Time':<8} {'Line Content'}")
        print("-" * 130)  # noqa: T201

        # Print top lines
        for line in all_lines[:top_n]:
            source_line = line["source_line"]
            if len(source_line) > 40:  # noqa: PLR2004
                source_line = source_line[:37] + "..."

            file_func = f"{line['file']}::{line['function']}"
            if len(file_func) > 50:  # noqa: PLR2004
                file_func = file_func[:47] + "..."

            print(f"{file_func:<50} {line['line_num']:<6} {line['hits']:<10} "  # noqa: T201
                  f"{line['time_us']:<13.1f} {line['avg_time_us']:<14.1f} "
                  f"{line['percent']:<8.1f} {source_line}")

        print("=" * 130)  # noqa: T201
        print()  # noqa: T201

    def get_stats(self) -> dict[tuple[str, str, int], FunctionStats]:
        """Get raw profiling statistics.

        Returns
        -------
            Dictionary mapping function keys to FunctionStats

        Test components:
        - Correct dictionary structure
        - Immutability considerations (returns reference, not copy)
        """
        return self._function_stats

    def clear(self) -> None:
        """Clear all profiling data.

        Test components:
        - Complete state reset
        - Proper dictionary clearing
        """
        self._function_stats.clear()
        self._last_time = 0.0
        self._last_line = None
        self._current_function_key = None

    def reset(self) -> None:
        """Reset the profiler to initial state (alias for clear).

        This method is an alias for clear() to provide a more intuitive
        interface for users who think of "resetting" rather than "clearing".

        Test components:
        - Verify it calls clear() correctly
        - Ensure all state is reset
        - Check it's safe to call multiple times
        """
        self.clear()
