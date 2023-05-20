#!/usr/bin/env python
# SPDX-FileCopyrightText: Copyright (c) 2022-2023, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

import pytest

import cudf

from morpheus.messages import MessageMeta
from morpheus.messages import MultiMessage
from morpheus.messages import MultiResponseMessage
from morpheus.pipeline import LinearPipeline
from morpheus.stages.input.in_memory_source_stage import InMemorySourceStage
from morpheus.stages.output.compare_dataframe_stage import CompareDataFrameStage
from morpheus.stages.postprocess.add_scores_stage import AddScoresStage
from morpheus.stages.postprocess.serialize_stage import SerializeStage
from morpheus.stages.preprocess.deserialize_stage import DeserializeStage
from stages.conv_msg import ConvMsg
from utils import assert_results
from utils import extend_df


@pytest.mark.slow
@pytest.mark.use_pandas
@pytest.mark.parametrize('order', ['F', 'C'])
@pytest.mark.parametrize('pipeline_batch_size', [256, 1024, 2048])
@pytest.mark.parametrize('repeat', [1, 10, 100])
def test_add_scores_stage_pipe(config, filter_probs_df, order, pipeline_batch_size, repeat):
    config.class_labels = ['frogs', 'lizards', 'toads', 'turtles']
    config.pipeline_batch_size = pipeline_batch_size

    input_df = filter_probs_df.copy(deep=True)
    if repeat > 1:
        input_df = extend_df(input_df, repeat)

    expected_df = filter_probs_df.rename(columns=dict(zip(filter_probs_df.columns, config.class_labels)))

    pipe = LinearPipeline(config)
    pipe.set_source(InMemorySourceStage(config, [cudf.DataFrame(input_df)]))
    pipe.add_stage(DeserializeStage(config))
    pipe.add_stage(ConvMsg(config, order=order, columns=list(input_df.columns)))
    pipe.add_stage(AddScoresStage(config))
    pipe.add_stage(SerializeStage(config, include=["^{}$".format(c) for c in config.class_labels]))
    comp_stage = pipe.add_stage(CompareDataFrameStage(config, expected_df))
    pipe.run()

    assert_results(comp_stage.get_results())


@pytest.mark.slow
@pytest.mark.use_pandas
@pytest.mark.parametrize('repeat', [1, 2, 5])
def test_add_scores_stage_multi_segment_pipe(config, filter_probs_df, repeat):
    # Intentionally using FileSourceStage's repeat argument as this triggers a bug in #443
    config.class_labels = ['frogs', 'lizards', 'toads', 'turtles']

    expected_df = filter_probs_df.rename(columns=dict(zip(filter_probs_df.columns, config.class_labels)))

    pipe = LinearPipeline(config)
    pipe.set_source(InMemorySourceStage(config, [cudf.DataFrame(filter_probs_df)], repeat=repeat))
    pipe.add_segment_boundary(MessageMeta)
    pipe.add_stage(DeserializeStage(config))
    pipe.add_segment_boundary(MultiMessage)
    pipe.add_stage(ConvMsg(config, columns=list(filter_probs_df.columns)))
    pipe.add_segment_boundary(MultiResponseMessage)
    pipe.add_stage(AddScoresStage(config))
    pipe.add_segment_boundary(MultiResponseMessage)
    pipe.add_stage(SerializeStage(config, include=["^{}$".format(c) for c in config.class_labels]))
    pipe.add_segment_boundary(MessageMeta)
    comp_stage = pipe.add_stage(CompareDataFrameStage(config, expected_df))
    pipe.run()

    assert_results(comp_stage.get_results())
