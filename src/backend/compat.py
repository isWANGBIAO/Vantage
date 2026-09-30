"""Compatibility exports for callers that historically imported ``src.server``.

Backend domains never import the legacy server module. Their ordinary functions
and module-qualified dependencies remain independently importable. This facade
only preserves old Python imports and test/development dependency overrides while
callers migrate to the appropriate domain. It does not register routes, load code,
copy function globals, or participate in HTTP dispatch.
"""
from types import ModuleType

from . import source_paths


class _LegacyServerModule(ModuleType):
    def __getattribute__(self, name):
        namespace = super().__getattribute__("__dict__")
        exports = namespace.get("_legacy_export_owners", {})
        if name == "__dict__":
            # unittest.mock checks __dict__ to decide whether a patched value
            # existed locally, including when create=True. Keep that view live.
            for exported_name, owners in exports.items():
                if hasattr(owners[0], exported_name):
                    namespace[exported_name] = getattr(owners[0], exported_name)
            return namespace
        owners = exports.get(name)
        if owners:
            return getattr(owners[0], name)
        return super().__getattribute__(name)

    def __setattr__(self, name, value):
        owners = self.__dict__.get("_legacy_export_owners", {}).get(name)
        if owners:
            for owner in owners:
                setattr(owner, name, value)
            super().__setattr__(name, value)
            return
        if name == "__file__":
            # Existing launch tests override the historical entry-point path.
            # Domain module __file__ values always keep their actual locations.
            source_paths.SERVER_FILE = value
        super().__setattr__(name, value)

    def __delattr__(self, name):
        owners = self.__dict__.get("_legacy_export_owners", {}).get(name)
        if owners:
            for owner in owners:
                delattr(owner, name)
            super().__delattr__(name)
            return
        super().__delattr__(name)

    def __dir__(self):
        return sorted(set(super().__dir__()) | self._legacy_export_owners.keys())


def install_legacy_exports(server_module, domain_modules):
    """Expose original symbols without storing stale copies in the server."""
    owners = {}
    for domain in domain_modules:
        for name, value in vars(domain).items():
            if name.startswith("__") or name in {"app", "router", "APIRouter", "bind_app"}:
                continue
            if isinstance(value, ModuleType) and value.__name__.startswith("src.backend"):
                continue
            if name in vars(server_module):
                # Composition-root imports and the application have real owners.
                continue
            previous = owners.setdefault(name, [])
            if previous and getattr(previous[0], name) is not value:
                raise RuntimeError(f"Conflicting compatibility export: {name}")
            previous.append(domain)
    for name, domains in owners.items():
        setattr(server_module, name, getattr(domains[0], name))
    server_module._legacy_export_owners = owners
    server_module.__class__ = _LegacyServerModule
    server_module.__all__ = ["app", "main", *sorted(owners)]
