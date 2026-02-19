# lineprofiler
Statistical profiler to find lines that take a long time to compute. One can specify a folder, wherein the profiler traces lines.
The profiler can be bound using `with`.

## Workflow
```python
from lineprofiler import LineProfiler
profiler = LineProfiler(project_folder="...<folder>...")
profiler.clear()
with profiler:
  ....<code>....
profiler.print_global_top_stats(min_time_us=0.01, top_n=40)
```

