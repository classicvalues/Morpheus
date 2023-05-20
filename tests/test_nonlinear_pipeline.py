#!/usr/bin/env python
# SPDX-FileCopyrightText: Copyright (c) 2023 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import typing

import mrc
import mrc.core.operators as ops
import pytest
from mrc.core.node import Broadcast

import cudf

from morpheus.config import Config
from morpheus.messages import MessageMeta
from morpheus.pipeline.pipeline import Pipeline
from morpheus.pipeline.stage import Stage
from morpheus.pipeline.stream_pair import StreamPair
from morpheus.stages.input.in_memory_source_stage import InMemorySourceStage
from morpheus.stages.output.compare_dataframe_stage import CompareDataFrameStage
from utils import assert_results


class SplitStage(Stage):

    def __init__(self, c: Config):
        super().__init__(c)

        self._create_ports(1, 2)

    @property
    def name(self) -> str:
        return "split"

    def supports_cpp_node(self):
        return False

    def _build(self, builder: mrc.Builder, in_ports_streams: typing.List[StreamPair]) -> typing.List[StreamPair]:

        assert len(in_ports_streams) == 1, "Only 1 input supported"

        # Create a broadcast node
        broadcast = Broadcast(builder, "broadcast")
        builder.make_edge(in_ports_streams[0][0], broadcast)

        def filter_higher_fn(data: MessageMeta):
            return MessageMeta(data.df[data.df["v2"] >= 0.5])

        def filter_lower_fn(data: MessageMeta):
            return MessageMeta(data.df[data.df["v2"] < 0.5])

        # Create a node that only passes on rows >= 0.5
        filter_higher = builder.make_node("filter_higher", ops.map(filter_higher_fn))
        builder.make_edge(broadcast, filter_higher)

        # Create a node that only passes on rows < 0.5
        filter_lower = builder.make_node("filter_lower", ops.map(filter_lower_fn))
        builder.make_edge(broadcast, filter_lower)

        return [(filter_higher, in_ports_streams[0][1]), (filter_lower, in_ports_streams[0][1])]


@pytest.mark.use_pandas
def test_forking_pipeline(config, filter_probs_df):
    compare_higher_df = filter_probs_df[filter_probs_df["v2"] >= 0.5]
    compare_lower_df = filter_probs_df[filter_probs_df["v2"] < 0.5]

    pipe = Pipeline(config)

    # Create the stages
    source = pipe.add_stage(InMemorySourceStage(config, [cudf.DataFrame(filter_probs_df)]))

    split_stage = pipe.add_stage(SplitStage(config))

    comp_higher = pipe.add_stage(CompareDataFrameStage(config, compare_df=compare_higher_df))
    comp_lower = pipe.add_stage(CompareDataFrameStage(config, compare_df=compare_lower_df))

    # Create the edges
    pipe.add_edge(source, split_stage)
    pipe.add_edge(split_stage.output_ports[0], comp_higher)
    pipe.add_edge(split_stage.output_ports[1], comp_lower)

    pipe.run()

    # Get the results
    assert_results(comp_higher.get_results())
    assert_results(comp_lower.get_results())
