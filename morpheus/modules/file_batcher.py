# Copyright (c) 2022-2023, NVIDIA CORPORATION.
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

import datetime
import logging
import re
from collections import namedtuple

import fsspec
import fsspec.utils
import mrc
from mrc.core import operators as ops

import cudf

from morpheus.messages import ControlMessage
from morpheus.utils.file_utils import date_extractor
from morpheus.utils.loader_ids import FILE_TO_DF_LOADER
from morpheus.utils.module_ids import FILE_BATCHER
from morpheus.utils.module_ids import MORPHEUS_MODULE_NAMESPACE
from morpheus.utils.module_utils import merge_dictionaries
from morpheus.utils.module_utils import register_module
from morpheus.utils.module_utils import to_period_cudf_approximation

logger = logging.getLogger(__name__)

default_iso_date_regex_pattern = (
    r"(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})"
    r"T(?P<hour>\d{1,2})(:|_)(?P<minute>\d{1,2})(:|_)(?P<second>\d{1,2})(?P<microsecond>\.\d{1,6})?Z")


@register_module(FILE_BATCHER, MORPHEUS_MODULE_NAMESPACE)
def file_batcher(builder: mrc.Builder):
    """
    This module loads the input files, removes files that are older than the chosen window of time,
    and then groups the remaining files by period that fall inside the window.


    Parameters
    ----------
    builder: mrc.Builder
        An mrc Builder object.

    Notes
    -----
        Configurable Parameters:
            - batching_options (dict): Options for batching; See below; Default: -
            - cache_dir (str): Cache directory; Example: `./file_batcher_cache`; Default: None
            - file_type (str): File type; Example: JSON; Default: JSON
            - filter_nulls (bool): Whether to filter null values; Example: false; Default: false
            - schema (dict): Data schema; See below; Default: `[Required]`
            - timestamp_column_name (str): Name of the timestamp column; Example: timestamp; Default: timestamp

        batching_options:
            - end_time (datetime/string): Endtime of the time window; Example: "2023-03-14T23:59:59"; Default: None
            - iso_date_regex_pattern (str): Regex pattern for ISO date matching;
            Example: "\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}"; Default: <iso_date_regex_pattern>
            - parser_kwargs (dict): Additional arguments for the parser; Example: {}; Default: {}
            - period (str): Time period for grouping files; Example: "1d"; Default: "1d"
            - sampling_rate_s (int): Sampling rate in seconds; Example: 60; Default: 60
            - start_time (datetime/string): Start time of the time window; Example: "2023-03-01T00:00:00"; Default: None

        schema:
            - encoding (str): Encoding; Example: "latin1"; Default: "latin1"
            - schema_str (str): Schema string; Example: "string"; Default: `[Required]`
    """

    config = builder.get_current_module_config()

    TimestampFileObj = namedtuple("TimestampFileObj", ["timestamp", "file_name"])

    iso_date_regex_pattern = config.get("batch_iso_date_regex_pattern", default_iso_date_regex_pattern)
    iso_date_regex = re.compile(iso_date_regex_pattern)

    default_batching_opts = {
        "period": config.get("period", 'D'),
        "sampling_rate_s": config.get("sampling_rate_s", 0),
        "start_time": config.get("start_time"),
        "end_time": config.get("end_time"),
    }

    def validate_control_message(control_message: ControlMessage):
        if control_message.has_metadata("batching_options") and not isinstance(
                control_message.get_metadata("batching_options"), dict):
            raise ValueError("Invalid or missing 'batching_options' metadata in control message")

        data_type = control_message.get_metadata("data_type")
        if data_type not in {"payload", "streaming"}:
            raise ValueError(f"Invalid 'data_type' metadata in control message: {data_type}")

    def build_fs_filename_df(files, params):
        file_objects: fsspec.core.OpenFiles = fsspec.open_files(files)

        try:
            start_time = params["start_time"]
            end_time = params["end_time"]
            sampling_rate_s = params["sampling_rate_s"]

            if not isinstance(start_time, (str, type(None))) or (start_time is not None
                                                                 and not re.match(r"\d{4}-\d{2}-\d{2}", start_time)):
                raise ValueError(f"Invalid 'start_time' value: {start_time}")

            if not isinstance(end_time, (str, type(None))) or (end_time is not None
                                                               and not re.match(r"\d{4}-\d{2}-\d{2}", end_time)):
                raise ValueError(f"Invalid 'end_time' value: {end_time}")

            if not isinstance(sampling_rate_s, int) or sampling_rate_s < 0:
                raise ValueError(f"Invalid 'sampling_rate_s' value: {sampling_rate_s}")

            if (start_time is not None):
                start_time = datetime.datetime.strptime(start_time, '%Y-%m-%d').replace(tzinfo=datetime.timezone.utc)

            if (end_time is not None):
                end_time = datetime.datetime.strptime(end_time, '%Y-%m-%d').replace(tzinfo=datetime.timezone.utc)

        except Exception as e:
            logger.error(f"Error parsing parameters: {e}")
            raise

        ts_and_files = []
        for file_object in file_objects:
            ts = date_extractor(file_object, iso_date_regex)

            # Exclude any files outside the time window
            if ((start_time is not None and ts < start_time) or (end_time is not None and ts > end_time)):
                continue

            ts_and_files.append(TimestampFileObj(ts, file_object.full_name))

        # sort the incoming data by date
        ts_and_files.sort(key=lambda x: x.timestamp)

        if ((len(ts_and_files) > 1) and (sampling_rate_s > 0)):
            file_sampled_list = []

            ts_last = ts_and_files[0].timestamp

            file_sampled_list.append(ts_and_files[0])

            for idx in range(1, len(ts_and_files)):
                ts = ts_and_files[idx].timestamp

                if ((ts - ts_last).seconds >= sampling_rate_s):
                    ts_and_files.append(ts_and_files[idx])
                    ts_last = ts
            else:
                ts_and_files = file_sampled_list

        timestamps = []
        full_names = []
        for (ts, file_name) in ts_and_files:
            timestamps.append(ts)
            full_names.append(file_name)

        df = cudf.DataFrame()
        df["ts"] = timestamps
        df["key"] = full_names

        return df

    def generate_cms_for_batch_periods(control_message: ControlMessage, period_gb, n_groups):
        data_type = control_message.get_metadata("data_type")

        control_messages = []
        for group in period_gb.groups:
            period_df = period_gb.get_group(group)
            filenames = period_df["key"].to_arrow().to_pylist()

            load_task = {
                "loader_id": FILE_TO_DF_LOADER,
                "strategy": "aggregate",
                "files": filenames,
                "n_groups": n_groups,
                "batcher_config": {  # TODO(Devin): Remove this when we're able to attach config to the loader
                    "timestamp_column_name": config.get("timestamp_column_name"),
                    "schema": config.get("schema"),
                    "file_type": config.get("file_type"),
                    "filter_null": config.get("filter_null"),
                    "parser_kwargs": config.get("parser_kwargs"),
                    "cache_dir": config.get("cache_dir")
                }
            }

            if (data_type == "payload"):
                control_message.add_task("load", load_task)
            elif (data_type == "streaming"):
                batch_control_message = control_message.copy()
                batch_control_message.add_task("load", load_task)
                control_messages.append(batch_control_message)
            else:
                raise Exception("Unknown data type")

        if (data_type == "payload"):
            control_messages.append(control_message)

        return control_messages

    def build_processing_params(control_message):
        batching_opts = {}
        if (control_message.has_metadata("batching_options")):
            batching_opts = control_message.get_metadata("batching_options")

        return merge_dictionaries(batching_opts, default_batching_opts)

    def on_data(control_message: ControlMessage):
        try:
            validate_control_message(control_message)

            mm = control_message.payload()
            params = build_processing_params(control_message)
            with mm.mutable_dataframe() as dfm:
                files = dfm.files.to_arrow().to_pylist()
                ts_filenames_df = build_fs_filename_df(files, params)

            control_messages = []
            if len(ts_filenames_df) > 0:
                # Now split by the batching settings

                ts_filenames_df = to_period_cudf_approximation(ts_filenames_df, params["period"])
                period_gb = ts_filenames_df.groupby("period")
                n_groups = len(period_gb.groups)

                control_messages = generate_cms_for_batch_periods(control_message, period_gb, n_groups)

            return control_messages
        except Exception as e:
            logger.error(f"Error building file list, discarding control message: {e}")
            return []

    def node_fn(obs: mrc.Observable, sub: mrc.Subscriber):
        obs.pipe(ops.map(on_data), ops.flatten()).subscribe(sub)

    node = builder.make_node(FILE_BATCHER, mrc.core.operators.build(node_fn))

    # Register input and output port for a module.
    builder.register_module_input("input", node)
    builder.register_module_output("output", node)
