# Profile sets in V7.12

V7.12 simplifies the profile landscape around a small set of generic embedded-product profiles.

## Generic ARM-embedded profiles
These profiles are intended for typical ARM-based embedded products:
- industrial_ctrl: industrial control and field I/O devices
- storage_gateway: storage-focused appliances and gateways
- network_product: routers, switches, and other network-centric products

Each profile is backed by a dedicated rule set under `configs/rules/`, plus shared keywords and
blacklists under `configs/rules/_shared/`.

You can extend or replace these profiles by adding new JSON files under `configs/profiles/` and
corresponding rule directories under `configs/rules/`, then updating your workspace config to
reference the new profile names in `active_profiles`.
