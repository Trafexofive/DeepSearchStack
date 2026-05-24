#
# services/search-agent/common/models.py
#
# Re-exporting common models for backward compatibility
# TODO: Eventually remove this file and update imports directly to libs.common.models

from libs.common.models import (
    Message,
    SearchResult,
    SynthesizeRequest,
    StreamingChunk
)
