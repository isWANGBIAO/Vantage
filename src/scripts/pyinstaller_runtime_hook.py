from src.core.cpu_runtime_policy import configure_cpu_runtime

configure_cpu_runtime()

from src.core.runtime_library_bootstrap import bootstrap_packaged_runtime_libraries


bootstrap_packaged_runtime_libraries()
