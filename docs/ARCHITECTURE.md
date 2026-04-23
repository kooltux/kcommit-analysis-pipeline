# Architecture

The pipeline is organized as restartable stages with shared helpers under `lib/`. Each stage reads cached outputs from previous stages and writes its own results back into the workspace cache.
