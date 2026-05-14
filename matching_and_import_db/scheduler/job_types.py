from enum import Enum


class PipelineRunType(str, Enum):
    COMPLETE = 'complete'
    ATLAS_CACHED = 'atlas_cached'