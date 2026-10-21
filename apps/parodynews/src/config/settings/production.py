"""Production settings for ParodyNews."""

import os

os.environ["RUNNING_IN_PRODUCTION"] = "True"
os.environ["DEBUG"] = "False"

from .base import *  # noqa: F403

IS_PRODUCTION = True
DEBUG = False
