from whitenoise.storage import CompressedManifestStaticFilesStorage


class ManifestStorage(CompressedManifestStaticFilesStorage):
    """Hashed static files that also rewrite JS `import ... from "./x.js"` to hashed names."""
    support_js_module_import_aggregation = True
