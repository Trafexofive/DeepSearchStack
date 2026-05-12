#
# services/search-gateway/common/models.py
#
# Re-exporting common models for backward compatibility
# TODO: Eventually remove this file and update imports directly to libs.common.models

from libs.common.models import (
    SearchProvider,
    SortMethod,
    SearchResult,
    SearchGatewayRequest
)
