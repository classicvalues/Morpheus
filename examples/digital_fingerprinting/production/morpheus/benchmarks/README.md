<!--
# Copyright (c) 2021-2023, NVIDIA CORPORATION.
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
-->

# Running DFP E2E Benchmarks

### Set Environment

To set up and run the benchmarks on production DFP pipeline, follow the instructions provided [here](../../README.md). Once the Morpheus container and the MLFlow server have been set up and running with `docker-compose`. Attach to the Morpheus pipeline container and download the sample data from S3 per the document's instructions.

## Requirements
> **Note**: Make sure `gputil`, `dask` and `distributed` are installed in your Conda environment before running the benchmarks. Run the installation command specified below if not.

```bash
conda install gputil dask==2022.7.0 distributed==2022.7.0
```

### Run E2E Benchmarks

Benchmarks are run using `pytest-benchmark`. By default, there are five rounds of measurement. For each round, there will be one iteration of each workflow. Measurements are taken for each round. Final results such as `min`, `max` and `mean` times will be based on these measurements.

To provide your own calibration or use other `pytest-benchmark` features with these workflows, please refer to their [documentation](https://pytest-benchmark.readthedocs.io/en/latest/).

Morpheus pipeline configurations for each workflow are managed using [pipelines_conf.json](./resource/pipelines_conf.json). For example, this is the Morpheus configuration for  `dfp_modules_duo_payload_inference`:
```
"test_dfp_modules_duo_payload_inference_e2e": {
		"message_path": "./resource/control_messages/duo_payload_inference.json",
		"num_threads": 12,
		"pipeline_batch_size": 256,
		"edge_buffer_size": 128,
		"start_time": "2022-08-01",
		"duration": "60d",
		"userid_column_name": "username",
		"timestamp_column_name": "timestamp",
		"source": "duo",
		"use_cpp": true
},
...
```

In addition to the Morpheus pipeline settings, we also have a configuration file called [modules_conf.json](./resource/modules_conf.json) that is specific to modules. When using MRC SegmentModule, pipelines need this configuration file. Additional information is included in the [Morpheus Pipeline with Modules](../../../../../docs/source/developer_guide/guides/6_digital_fingerprinting_reference.md#morpheus-pipeline-with-modules)

To ensure that the [file_to_df_loader.py](../../../../../morpheus/loaders/file_to_df_loader.py) utilizes the same type of downloading mechanism, set `MORPHEUS FILE DOWNLOAD TYPE` environment variable with any one of given choices (`multiprocess`, `dask`, `dask thread`, `single thread`).

```
export MORPHEUS_FILE_DOWNLOAD_TYPE=multiprocess
```

Benchmarks for an individual workflow can be run using the following:

```

pytest -s --log-level=WARN --benchmark-enable --benchmark-warmup=on --benchmark-warmup-iterations=1 --benchmark-autosave test_bench_e2e_dfp_pipeline.py::<test-workflow>
```
The `-s` option allows outputs of pipeline execution to be displayed so you can ensure there are no errors while running your benchmarks.

The `--benchmark-warmup` and `--benchmark-warmup-iterations` options are used to run the workflow(s) once before starting measurements. This is because, if it does not already exist, the preprocessed data is cached during the initial run.

`<test-workflow>` is the name of the test to run benchmarks on. This can be one of the following:
- `test_dfp_modules_azure_payload_inference_e2e`
- `test_dfp_modules_azure_payload_lti_e2e`
- `test_dfp_modules_azure_payload_training_e2e`
- `test_dfp_modules_azure_streaming_inference_e2e`
- `test_dfp_modules_azure_streaming_lti_e2e`
- `test_dfp_modules_azure_streaming_training_e2e`
- `test_dfp_modules_duo_payload_inference_e2e`
- `test_dfp_modules_duo_payload_lti_e2e`
- `test_dfp_modules_duo_payload_only_load_e2e`
- `test_dfp_modules_duo_payload_training_e2e`
- `test_dfp_modules_duo_streaming_inference_e2e`
- `test_dfp_modules_duo_streaming_lti_e2e`
- `test_dfp_modules_duo_streaming_only_load_e2e`
- `test_dfp_modules_duo_streaming_payload_e2e`
- `test_dfp_modules_duo_streaming_training_e2e`
- `test_dfp_stages_azure_training_e2e`
- `test_dfp_stages_azure_inference_e2e`
- `test_dfp_stages_duo_training_e2e`
- `test_dfp_stages_duo_inference_e2e`

For example, to run E2E benchmarks on the DFP training (modules) workflow on the duo logs:
```
pytest -s --benchmark-enable --benchmark-warmup=on --benchmark-warmup-iterations=1 --benchmark-autosave test_bench_e2e_dfp_pipeline.py::test_dfp_modules_azure_payload_lti_e2e
```

To run E2E benchmarks on all workflows:
```
pytest -s --benchmark-enable --benchmark-warmup=on --benchmark-warmup-iterations=1 --benchmark-autosave test_bench_e2e_dfp_pipeline.py
```

The console output should look like this:
```
-------------------------------------------------------------------------------------------------------- benchmark: 19 tests --------------------------------------------------------------------------------------------------------
Name (time in ms)                                          Min                    Max                   Mean              StdDev                 Median                 IQR            Outliers     OPS            Rounds  Iterations
-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
TODO: Add benchmark results here -- need to do different runs for training vs inference vs everything else
-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
```

### Benchmarks Report

Each time you run the benchmarks as above, a comprehensive report for each run will be generated and saved to a JSON file in  `./benchmarks/.benchmarks`. The file name will begin
with `000N` where N is incremented for every run. For example, the report file name for first benchmarks run will look like:
```
0001_f492e1952d5981527d89229e557006a1db992e5f_20230201_230822.json
```

A hook to `pytest-benchmark` was developed to add the following information to the JSON report:

GPU(s) used by Morpheus. For example:
```
"gpu_0": {
    "id": 0,
    "name": "Quadro RTX 8000",
    "load": "0.0%",
    "free_memory": "47627.0MB",
    "used_memory": "965.0MB",
    "temperature": "55.0 C",
    "uuid": "GPU-6fa37f47-763b-fc49-1b15-75b0d36525bf"
}
```

Morpheus config for each workflow:
- num_threads
- pipeline_batch_size
- edge_buffer_size
- start_time
- duration
- userid_column_name
- timestamp_column_name
- source
- use_cpp

Additional benchmark stats for each workflow:
- input_lines
- min_throughput_lines
- max_throughput_lines
- mean_throughput_lines
- median_throughput_lines
- input_bytes
- min_throughput_bytes
- max_throughput_bytes
- mean_throughput_bytes
- median_throughput_bytes
