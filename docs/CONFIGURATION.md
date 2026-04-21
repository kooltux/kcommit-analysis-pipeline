# Configuration Guide

## V6.2 config behavior
- `include_configs` supports relative paths.
- Strings support `${foo}` pseudo variables.
- Built-in variables include `${config_dir}` and `${cwd}`.
## V6.7 workspace rule

All example configs must avoid hardcoded absolute paths.
Use the external variable `WORKSPACE` as the base for every path.
A typical invocation pattern is to export `WORKSPACE` in the shell and pass it through config variables so every source, build, log, and work directory is derived from `${WORKSPACE}`.
## V6.8 WORKSPACE environment behavior

`WORKSPACE` may now be provided by the shell environment.
If you export `WORKSPACE` before launching the pipeline, the config loader imports it automatically and uses it to expand `${WORKSPACE}` in config files.

Example:

```sh
export WORKSPACE=$HOME/my-product
./launch.sh ./configs/example--qcom-tcu.json
```
## V6.9 mandatory and optional inputs

The following inputs are mandatory:
- `kernel.source_dir`
- `inputs.kernel_config`

The following input is optional:
- `inputs.build_dir`

If `build_dir` exists, its `.o` and `.ko` artifacts are scanned and included in the build context and product map.
If `build_dir` is missing or unset, the pipeline continues without it.

## V7.8 TOOLDIR and WORKSPACE split
`TOOLDIR` identifies the tool repository root, typically the directory that contains the top-level `Makefile`.
`WORKSPACE` identifies the product workspace holding the kernel source tree, kernel config, logs, and optional build directory.
These two roots can now be separated, which allows custom configuration, profiles, and rules to live in another repository while the analyzed product data stays under a different workspace.
Profiles and rules are now stored under `configs/` using relative paths whenever possible.
