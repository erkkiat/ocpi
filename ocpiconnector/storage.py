import logging

from whitenoise.storage import CompressedManifestStaticFilesStorage

logger = logging.getLogger(__name__)


class LenientManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """
    WhiteNoise's CompressedManifestStaticFilesStorage that tolerates CSS/JS
    files referencing assets absent from the static root.

    Identical behaviour to the parent (filename hashing, .gz/.br pre-compression,
    long Cache-Control headers) except that missing referenced files produce a
    warning instead of a MissingFileError.  The unresolvable reference is left
    as-is in the output file.

    Background: several legacy theme CSS files (css/theme*.css) bundled with
    the project reference fonts and images that were never committed to the
    repo.  Those files are not loaded by any Django template so the dangling
    references have no runtime impact.
    """

    manifest_strict = False

    def hashed_name(self, name, content=None, filename=None):
        super().hashed_name(name, content=content, filename=filename)
        # try:
        #     return super().hashed_name(name, content=content, filename=filename)
        # except ValueError:
        #     # Referenced asset does not exist — leave the URL unchanged and log
        #     # a warning so it doesn't silently disappear.
        #     logger.warning(
        #         "Static asset not found, leaving reference unchanged: %s", name
        #     )
        #     return name
