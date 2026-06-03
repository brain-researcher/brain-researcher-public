"""Multi-backend runtime support for Brain Researcher.

This package provides support for executing neuroimaging jobs across multiple
backend platforms including Kubernetes, SLURM, and AWS Batch with intelligent
selection and transparent failover.
"""

from .base_backend import (
    BaseBackend,
    JobSpecification,
    JobStatus,
    JobState,
    ResourceRequirements,
    BackendCapacity,
    BackendError,
    BackendSubmissionError,
    JobNotFoundError,
    BackendUnavailableError,
    BackendConfigError
)

from .backend_selector import (
    BackendSelector,
    SelectionStrategy,
    BackendScore
)

# Backend implementations
from .kubernetes_backend import KubernetesBackend
from .slurm_backend import SLURMBackend
from .aws_batch_backend import AWSBatchBackend
from .neurodesk_backend import NeurodeskBackend

__all__ = [
    # Base classes and types
    'BaseBackend',
    'JobSpecification',
    'JobStatus',
    'JobState',
    'ResourceRequirements',
    'BackendCapacity',

    # Exceptions
    'BackendError',
    'BackendSubmissionError',
    'JobNotFoundError',
    'BackendUnavailableError',
    'BackendConfigError',

    # Selection and management
    'BackendSelector',
    'SelectionStrategy',
    'BackendScore',

    # Backend implementations
    'KubernetesBackend',
    'SLURMBackend',
    'AWSBatchBackend',
    'NeurodeskBackend',
]

# Version info
__version__ = '1.0.0'
__author__ = 'Brain Researcher Team'
__description__ = 'Multi-backend runtime support for neuroimaging workloads'