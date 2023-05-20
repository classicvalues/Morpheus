# Copyright (c) 2023, NVIDIA CORPORATION.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import typing
from datetime import datetime

import click
import dfp.modules.dfp_deployment  # noqa: F401
from dfp.utils.config_generator import ConfigGenerator
from dfp.utils.config_generator import generate_ae_config
from dfp.utils.dfp_arg_parser import DFPArgParser
from dfp.utils.schema_utils import Schema
from dfp.utils.schema_utils import SchemaBuilder

from morpheus.cli.utils import get_log_levels
from morpheus.cli.utils import parse_log_level
from morpheus.config import Config
from morpheus.pipeline.pipeline import Pipeline
from morpheus.stages.general.monitor_stage import MonitorStage
from morpheus.stages.general.multiport_modules_stage import MultiPortModulesStage
from morpheus.stages.input.control_message_file_source_stage import ControlMessageFileSourceStage


@click.command()
@click.option(
    "--source",
    type=click.Choice(["duo", "azure"], case_sensitive=False),
    required=True,
    help=("Indicates what type of logs are going to be used in the workload."),
)
@click.option(
    "--train_users",
    type=click.Choice(["all", "generic", "individual"], case_sensitive=False),
    help=("Indicates whether or not to train per user or a generic model for all users. "
          "Selecting none runs the inference pipeline."),
)
@click.option(
    "--skip_user",
    multiple=True,
    type=str,
    help="User IDs to skip. Mutually exclusive with only_user",
)
@click.option(
    "--only_user",
    multiple=True,
    type=str,
    help="Only users specified by this option will be included. Mutually exclusive with skip_user",
)
@click.option(
    "--start_time",
    type=click.DateTime(
        formats=['%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%d %H:%M:%S%z']),
    default=None,
    help="The start of the time window, if undefined start_date will be `now()-duration`",
)
@click.option(
    "--duration",
    type=str,
    default="60d",
    help="The training duration to run starting from start_time",
)
@click.option(
    "--use_cpp",
    type=click.BOOL,
    default=False,
    help=("Indicates what type of logs are going to be used in the workload."),
)
@click.option(
    "--cache_dir",
    type=str,
    default="./.cache/dfp",
    show_envvar=True,
    help="The location to cache data such as S3 downloads and pre-processed data",
)
@click.option("--log_level",
              default=logging.getLevelName(Config().log_level),
              type=click.Choice(get_log_levels(), case_sensitive=False),
              callback=parse_log_level,
              help="Specify the logging level to use.")
@click.option("--sample_rate_s",
              type=int,
              default=0,
              show_envvar=True,
              help="Minimum time step, in milliseconds, between object logs.")
@click.option(
    "--input_file",
    "-f",
    type=str,
    multiple=True,
    help=("List of files to process. Can specify multiple arguments for multiple files. "
          "Also accepts glob (*) wildcards and schema prefixes such as `s3://`. "
          "For example, to make a local cache of an s3 bucket, use `filecache::s3://mybucket/*`. "
          "See fsspec documentation for list of possible options."),
)
@click.option('--tracking_uri',
              type=str,
              default="http://mlflow:5000",
              help=("The MLflow tracking URI to connect to the tracking backend."))
def run_pipeline(source: str,
                 train_users: str,
                 skip_user: typing.Tuple[str],
                 only_user: typing.Tuple[str],
                 start_time: datetime,
                 duration: str,
                 cache_dir: str,
                 log_level: int,
                 sample_rate_s: int,
                 tracking_uri,
                 use_cpp,
                 **kwargs):
    if (skip_user and only_user):
        logging.error("Option --skip_user and --only_user are mutually exclusive. Exiting")

    dfp_arg_parser = DFPArgParser(skip_user,
                                  only_user,
                                  start_time,
                                  log_level,
                                  cache_dir,
                                  sample_rate_s,
                                  duration,
                                  source,
                                  tracking_uri,
                                  train_users)

    dfp_arg_parser.init()

    # Default user_id column -- override with ControlMessage
    userid_column_name = "username"
    # Default timestamp column -- override with ControlMessage
    timestamp_column_name = "timestamp"

    config: Config = generate_ae_config(source, userid_column_name, timestamp_column_name, use_cpp=use_cpp)

    # Construct the data frame Schema used to normalize incoming data
    schema_builder = SchemaBuilder(config, source)
    schema: Schema = schema_builder.build_schema()

    # Create config helper used to generate config parameters for the DFP module
    # This will populate to the minimum configuration parameters with intelligent default values
    config_generator = ConfigGenerator(config, dfp_arg_parser, schema)

    dfp_deployment_module_config = config_generator.get_module_conf()

    # Create a pipeline object
    pipeline = Pipeline(config)

    source_stage = pipeline.add_stage(ControlMessageFileSourceStage(config, filenames=list(kwargs["input_file"])))

    dfp_deployment_stage = pipeline.add_stage(
        MultiPortModulesStage(config,
                              dfp_deployment_module_config,
                              input_port_name="input",
                              output_port_name_prefix="output",
                              num_output_ports=2))

    train_moniter_stage = pipeline.add_stage(
        MonitorStage(config, description="DFP Training Pipeline rate", smoothing=0.001))

    infer_moniter_stage = pipeline.add_stage(
        MonitorStage(config, description="DFP Inference Pipeline rate", smoothing=0.001))

    pipeline.add_edge(source_stage, dfp_deployment_stage)
    pipeline.add_edge(dfp_deployment_stage.output_ports[0], train_moniter_stage)
    pipeline.add_edge(dfp_deployment_stage.output_ports[1], infer_moniter_stage)

    # Run the pipeline
    pipeline.run()


if __name__ == "__main__":
    run_pipeline(obj={}, auto_envvar_prefix='DFP', show_default=True, prog_name="dfp")
