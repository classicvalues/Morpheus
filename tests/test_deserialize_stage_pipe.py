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

from morpheus.messages import MessageMeta
from morpheus.pipeline import LinearPipeline
from morpheus.stages.input.in_memory_source_stage import InMemorySourceStage
from morpheus.stages.output.compare_dataframe_stage import CompareDataFrameStage
from morpheus.stages.postprocess.serialize_stage import SerializeStage
from morpheus.stages.preprocess.deserialize_stage import DeserializeStage
from utils import assert_df_equal
from utils import assert_results
from utils import duplicate_df_index
from utils import duplicate_df_index_rand


@pytest.mark.use_cudf
def test_fixing_non_unique_indexes(use_cpp, filter_probs_df):
    # Set 2 ids equal to others
    df = duplicate_df_index_rand(filter_probs_df, count=2)

    meta = MessageMeta(df.copy())

    assert not meta.has_sliceable_index(), "Need to start with a non-sliceable index"

    # When processing the dataframe, a warning should be generated when there are non-unique IDs
    with pytest.warns(RuntimeWarning):

        DeserializeStage.process_dataframe(meta, 5, ensure_sliceable_index=False)

        assert not meta.has_sliceable_index()
        assert "_index_" not in meta.df.columns

    assert assert_df_equal(meta.df, df)

    DeserializeStage.process_dataframe(meta, 5, ensure_sliceable_index=True)

    assert meta.has_sliceable_index()
    assert "_index_" in meta.df.columns


@pytest.mark.use_cudf
@pytest.mark.parametrize("dup_index", [False, True])
def test_deserialize_pipe(config, filter_probs_df, dup_index: bool):
    """
    End to end test for DeserializeStage
    """
    expected_df = filter_probs_df.to_pandas()  # take a copy before we mess with the index

    if dup_index:
        filter_probs_df = duplicate_df_index(filter_probs_df, {8: 7})

    pipe = LinearPipeline(config)
    pipe.set_source(InMemorySourceStage(config, [filter_probs_df]))
    pipe.add_stage(DeserializeStage(config))
    pipe.add_stage(SerializeStage(config, include=[r'^v\d+$']))
    comp_stage = pipe.add_stage(CompareDataFrameStage(config, expected_df))
    pipe.run()

    assert_results(comp_stage.get_results())


@pytest.mark.use_cudf
@pytest.mark.parametrize("dup_index", [False, True])
def test_deserialize_multi_segment_pipe(config, filter_probs_df, dup_index: bool):
    """
    End to end test across mulitiple segments
    """
    expected_df = filter_probs_df.to_pandas()  # take a copy before we mess with the index

    if dup_index:
        filter_probs_df = duplicate_df_index(filter_probs_df, {8: 7})

    pipe = LinearPipeline(config)
    pipe.set_source(InMemorySourceStage(config, [filter_probs_df]))
    pipe.add_segment_boundary(MessageMeta)
    pipe.add_stage(DeserializeStage(config))
    pipe.add_stage(SerializeStage(config, include=[r'^v\d+$']))
    comp_stage = pipe.add_stage(CompareDataFrameStage(config, expected_df))
    pipe.run()

    assert_results(comp_stage.get_results())
