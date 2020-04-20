# -*- coding: utf-8 -*-

"""Local analysis engine manager"""

import logging

from schema import SchemaError
from cbc_binary_toolkit import InitializationError
from cbc_binary_toolkit.loader import dynamic_create
from cbc_binary_toolkit.schemas import BinaryMetadataSchema

log = logging.getLogger(__name__)


class LocalEngineFactory():
    """Abstract base class that should be inherited by Engine Factory objects."""
    def create_engine(self, config):
        """
        Creates a new Engine thread

        Args:
            config (cbc_binary_toolkit.Config): cbc_binary_toolkit Config object

        """
        raise NotImplementedError("protocol not implemented: create_engine")


class LocalEngineManager():
    """
    High level manager for Analysis Engines that passes through to Engine threads

    Initializes and manages the threaded analysis engines

    """

    def __init__(self, config):
        """Constructor"""
        self.config = config

        if not self.config.get("engine.local"):
            raise InitializationError
        self.engine_factory = dynamic_create(self.config.string("engine._provider"))
        self.engine = self.engine_factory.create_engine(self.config.section("engine"))

    def create_engine(self):
        """Creates engine"""
        return self.engine_factory.create_engine(self.config.section("engine"))

    def analyze(self, binary_metadata):
        """Sends HashMetadata to engine"""
        try:
            valid_metadata = BinaryMetadataSchema.validate(binary_metadata)
            return self.engine.analyze(valid_metadata)
        except SchemaError as e:
            log.error(f"Invalid schema for binary_metadata: {e}")
            return {
                "iocs": [],
                "engine_name": self.engine.name,
                "binary_hash": binary_metadata.get("sha256", None) if isinstance(binary_metadata, dict) else None,
                "success": False
            }
