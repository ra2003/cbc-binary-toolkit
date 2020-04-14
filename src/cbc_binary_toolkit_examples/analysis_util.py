# -*- coding: utf-8 -*-

"""
Binary analysis sdk for managing and submitting hashes

This class performs binary analysis on a series of hashes passed in on the command line.
"""

import argparse
import logging

from datetime import datetime

from cbc_binary_toolkit import cli_input
from cbc_binary_toolkit import EngineResults
from cbc_binary_toolkit.config import Config
from cbc_binary_toolkit.deduplication_component import DeduplicationComponent
from cbc_binary_toolkit.ingestion_component import IngestionComponent
from cbc_binary_toolkit.engine import LocalEngineManager
from cbc_binary_toolkit.state import StateManager

from cbapi import CbThreatHunterAPI

log = logging.getLogger(__name__)


class AnalysisUtility:
    """The top level analysis utility class. This is intended as an example which can be modified as needed."""
    def __init__(self, default_install):
        """Constructor for the analysis utility class"""
        self.default_install = default_install
        self.config = None
        self.cbapi = None

        # Create argument parser
        self._parser = argparse.ArgumentParser()
        self._parser.add_argument("-c", "--config", type=str, default=default_install,
                                  help="Location of the configuration file (default {0})".format(default_install))

        commands = self._parser.add_subparsers(help="Binary analysis commands", dest="command_name", required=True)

        # Analyze command parser
        analyze_command = commands.add_parser("analyze", help="Analyze a list of hashes by command line or file")
        input_type = analyze_command.add_mutually_exclusive_group(required=True)
        input_type.add_argument("-l", "--list", type=str, help="List of hashes in JSON string format")
        input_type.add_argument("-f", "--file", type=argparse.FileType('r'),
                                help="File of hashes in json or csv format")

        # Restart command parser
        commands.add_parser("restart", help="Restart a failed job and pick up where the job crashed or exited")

        # Clear command parser
        clear_command = commands.add_parser("clear", help="Clear cache of analyzed hashes. All or by timestamp")
        clear_command.add_argument("-t", "--timestamp", type=str,
                                   help="ISO 8601 date format {YYYY-MM-DD HH:MM:SS.SSS}")

    def _init_components(self):
        """
        Initialize the components of the toolkit, injecting their dependencies as they're created.

        Returns:
            dict: A dict containing all the references to the top-level components.
        """
        state_manager = StateManager(self.config)

        cbth = self.cbapi
        if cbth is None:
            cbth = CbThreatHunterAPI(url=self.config.get("carbonblackcloud.url"),
                                     org_key=self.config.get("carbonblackcloud.org_key"),
                                     token=self.config.get("carbonblackcloud.api_token"),
                                     ssl_verify=self.config.get("carbonblackcloud.ssl_verify"))

        deduplicate = DeduplicationComponent(self.config, state_manager)
        ingest = IngestionComponent(self.config, cbth, state_manager)

        results_engine = EngineResults(self.config.get("engine.name"), state_manager, cbth)
        if self.config.get("engine.local"):
            engine_manager = LocalEngineManager(self.config)

        return {
            "deduplicate": deduplicate,
            "ingest": ingest,
            "engine_manager": engine_manager,
            "results_engine": results_engine,
            "state_manager": state_manager
        }

    def _yes_or_no(self, question):
        """
        Request confirmation of something from the user.

        Args:
            question (str): Question to ask the user.

        Returns:
            boolean: True if the user answered Yes, False if they answered No.
        """
        reply = str(input(f"{question}: (y/n)")).lower().strip()
        if reply[0] == 'y':
            return True
        if reply[0] == 'n':
            return False
        else:
            log.error("Invalid: please use y/n")
            return self._yes_or_no(question)

    def _process_metadata(self, components, metadata_list):
        """
        Analyze a list of metadata through the analysis engine and report on the results.
        The back end to the analyze and restart commands.

        Args:
            components (dict): Dict containing all the component references as returned from _init_components.
            metadata_list (list): List of metadata objects to be analyzed.
        """
        for metadata in metadata_list:
            response = components["engine_manager"].analyze(metadata)
            components["results_engine"].receive_response(response)

        components["results_engine"].send_reports(self.config.get("engine.feed_id"))

    def _analyze_command(self, args, components):
        """
        Implements the "analyze" command to analyze a list of hashes.

        Args:
            args (Namespace): The command-line arguments as parsed.
            components (dict): Dict containing all the component references as returned from _init_components.
        """
        if args.file is not None:
            hash_group = cli_input.read_csv(args.file)
        else:
            hash_group = cli_input.read_json(args.list)

        hash_group = components["deduplicate"].deduplicate(hash_group)
        metadata_list = components["ingest"].fetch_metadata(hash_group)
        self._process_metadata(components, metadata_list)

    def _restart_command(self, components):
        """
        Implements the "restart" command to resume analysis on already-ingested hash values.

        Args:
            components (dict): Dict containing all the component references as returned from _init_components.
        """
        metadata_list = components["ingest"].reload()
        self._process_metadata(components, metadata_list)

    def main(self, cmdline_args):
        """
        Entry point for the analysis utility.

        Args:
            cmdline_args (list): Command-line argument strings to be parsed.

        Returns:
            int: Return code from the utility (0=success, nonzero=failure).
        """
        log.info("Started: {}".format(datetime.now()))

        args = self._parser.parse_args(cmdline_args)

        try:
            if self.config is None:
                if args.config != self.default_install:
                    self.config = Config.load_file(args.config)
                else:
                    log.info(f"Attempting to load config from {self.default_install}")
                    self.config = Config.load_file(self.default_install)

            if args.command_name == "analyze":
                log.info("Analyzing hashes")
                components = self._init_components()
                self._analyze_command(args, components)

            elif args.command_name == "clear":
                log.info("Clear cache")

                timestamp = args.timestamp
                if timestamp is None:
                    timestamp = str(datetime.now())
                if not self._yes_or_no(f"Confirm you want to clear runs since {timestamp}"):
                    log.info("Clear canceled")
                    return

                # Clear previous states
                state_manager = StateManager(self.config)
                state_manager.prune(timestamp)

            elif args.command_name == "restart":
                log.info("Restart")
                components = self._init_components()
                self._restart_command(components)

            log.info("Finished: {}".format(datetime.now()))
            return 0
        except Exception as ex:
            print(ex)
            return 1