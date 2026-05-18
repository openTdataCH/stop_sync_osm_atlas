from enum import Enum


class PipelineRunType(str, Enum):
    COMPLETE = 'complete'
    ATLAS_CACHED = 'atlas_cached'
    ATLAS_CACHED_BOOTSTRAP = 'atlas_cached_bootstrap'